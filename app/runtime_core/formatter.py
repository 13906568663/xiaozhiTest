"""Format ``Msg`` history into OpenAI Chat Completions API request payload.

Output 形状（兼容 OpenAI、DeepSeek、通义、Moonshot 等）::

    [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "...", "tool_calls": [{...}]},
        {"role": "tool", "tool_call_id": "...", "content": "..."},
    ]

特殊处理：
  * 一条 ``Msg(role="system", blocks=[tool_result, tool_result])`` 会被拆成
    多条 ``role="tool"`` 条目（OpenAI 协议要求 tool 消息一对一）。
  * ``DeepSeek`` 模式下，``thinking`` block 会被丢弃（DeepSeek 不接受历史里
    的 ``reasoning_content``）。
  * ``promote_tool_result_images=True``：tool_result 后面跟着图片 block 时，
    把图片单独放到一个新的 ``role="user"`` 消息里上送（部分供应商不支持
    tool 消息里嵌图）。
  * ``compressed_summary``：调用方传入时，formatter 会在最前面以一条
    ``role="system"`` 注入。新版（fool-code 风格）摘要文本本身已包含
    "本次会话是从之前对话延续的..." preamble，formatter 直接原文注入；
    旧版裸摘要文本则会被自动加上「[历史会话摘要]」前缀以兼容。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from app.runtime_core.messages import Msg, MsgRole


class ChatFormatter:
    def __init__(
        self,
        *,
        deepseek_compat: bool = False,
        promote_tool_result_images: bool = False,
    ) -> None:
        self.deepseek_compat = deepseek_compat
        self.promote_tool_result_images = promote_tool_result_images

    def format(
        self,
        messages: Iterable[Msg],
        *,
        sys_prompt: str | None = None,
        compressed_summary: str | None = None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if sys_prompt:
            result.append({"role": "system", "content": sys_prompt})
        if compressed_summary:
            # 新版摘要（compression.get_compact_continuation_message）已经自带
            # "本次会话是从之前的对话延续的..." preamble + 末尾续接指令，直接
            # 原文注入即可；旧版裸摘要则补一个传统前缀，避免模型把它当成普通
            # system 指令。这里通过检测 fool-code preamble 头来区分。
            _NEW_PREAMBLE = "本次会话是从之前的对话延续的"
            if compressed_summary.lstrip().startswith(_NEW_PREAMBLE):
                result.append({"role": "system", "content": compressed_summary})
            else:
                result.append({
                    "role": "system",
                    "content": (
                        "[历史会话摘要 - 上一段较长的对话已被压缩为以下摘要]\n"
                        + compressed_summary
                    ),
                })

        promoted_images: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.role
            blocks = msg.blocks

            if role == MsgRole.USER:
                entry = self._format_user_or_assistant("user", blocks)
                if entry:
                    result.append(entry)

            elif role == MsgRole.ASSISTANT:
                entry = self._format_user_or_assistant("assistant", blocks)
                if entry:
                    result.append(entry)

            elif role == MsgRole.SYSTEM:
                # SYSTEM role 在我们这里通常承载 tool_result 观察值。
                # 把每个 tool_result block 单独翻译成 role="tool"。
                tool_results = [b for b in blocks if b.get("type") == "tool_result"]
                if tool_results:
                    for tr in tool_results:
                        result.append({
                            "role": "tool",
                            "tool_call_id": str(tr.get("id") or ""),
                            "content": _stringify_tool_output(tr.get("output")),
                        })
                    if self.promote_tool_result_images:
                        for b in blocks:
                            if b.get("type") == "image":
                                promoted_images.append(_image_to_user_block(b))
                    continue

                # 否则当成普通 system 文案
                text = _join_text(blocks)
                if text:
                    result.append({"role": "system", "content": text})

        if promoted_images:
            result.append({
                "role": "user",
                "content": [{"type": "text", "text": "[Tool returned images]"}] + promoted_images,
            })

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_user_or_assistant(
        self, role: str, blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        text_parts: list[str] = []
        multimodal_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        any_image = False

        for b in blocks:
            t = b.get("type")
            if t == "text":
                txt = b.get("text") or ""
                if txt:
                    text_parts.append(txt)
            elif t == "thinking":
                # 历史里的 thinking 不发回模型；DeepSeek 严格禁止。
                continue
            elif t == "image":
                any_image = True
                multimodal_parts.append(_image_to_user_block(b))
            elif t == "tool_use" and role == "assistant":
                input_payload = b.get("input")
                if isinstance(input_payload, dict):
                    args = json.dumps(input_payload, ensure_ascii=False)
                else:
                    args = str(input_payload or "{}")
                tool_calls.append({
                    "id": str(b.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(b.get("name") or ""),
                        "arguments": args,
                    },
                })

        entry: dict[str, Any] = {"role": role}
        if any_image:
            content_parts: list[Any] = []
            for txt in text_parts:
                content_parts.append({"type": "text", "text": txt})
            content_parts.extend(multimodal_parts)
            entry["content"] = content_parts
        elif text_parts:
            entry["content"] = "\n".join(text_parts)
        else:
            entry["content"] = "" if not tool_calls else None

        if tool_calls and role == "assistant":
            entry["tool_calls"] = tool_calls
            if entry.get("content") is None:
                entry["content"] = ""
            elif self.deepseek_compat and entry.get("content") == "":
                # DeepSeek 要求带 tool_calls 的 assistant 消息 content 必须为字符串。
                entry["content"] = ""

        if entry.get("content") is None and not tool_calls:
            return None
        return entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stringify_tool_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _join_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for b in blocks:
        if b.get("type") == "text" and b.get("text"):
            parts.append(str(b["text"]))
    return "\n".join(parts)


def _image_to_user_block(block: dict[str, Any]) -> dict[str, Any]:
    """Convert an image content block to OpenAI ``image_url`` content part."""
    media = block.get("media_type") or "image/png"
    if block.get("url"):
        return {"type": "image_url", "image_url": {"url": str(block["url"])}}
    if block.get("data"):
        # Assume base64
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media};base64,{block['data']}"},
        }
    return {"type": "text", "text": "[Image unavailable]"}


__all__ = ["ChatFormatter"]
