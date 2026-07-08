"""Conversation message model.

Design goals:
  * 内部结构干净，只有 ``role`` / ``blocks`` / ``metadata``。
  * ``to_dict()`` / ``from_dict()`` 字段为 (role / name / content / metadata)，
    方便存量 session_memory 数据无痛迁移。
  * Block 类型限定为 ``text`` / ``tool_use`` / ``tool_result`` / ``image``
    / ``thinking`` / ``audio``，其余字段忽略。

ContentBlock 字段名沿用 OpenAI ChatCompletion 习惯：
    text         {type: "text", text: str}
    tool_use     {type: "tool_use", id, name, input(dict)}
    tool_result  {type: "tool_result", id, name, output(str), is_error?}
    image        {type: "image", url|data, media_type}
    thinking     {type: "thinking", text}
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class MsgRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ContentBlock 用 dict 表示，避免 pydantic 校验开销，也方便兼容多种历史格式。
ContentBlock = dict[str, Any]


def text_block(text: str) -> ContentBlock:
    return {"type": "text", "text": text}


def tool_use_block(call_id: str, name: str, input_: dict[str, Any]) -> ContentBlock:
    return {
        "type": "tool_use",
        "id": call_id,
        "name": name,
        "input": dict(input_) if input_ else {},
    }


def tool_result_block(
    call_id: str,
    name: str,
    output: Any,
    *,
    is_error: bool = False,
) -> ContentBlock:
    block: ContentBlock = {
        "type": "tool_result",
        "id": call_id,
        "name": name,
        "output": output,
    }
    if is_error:
        block["is_error"] = True
    return block


def image_block(
    *,
    url: str | None = None,
    data: str | None = None,
    media_type: str = "image/png",
) -> ContentBlock:
    block: ContentBlock = {"type": "image", "media_type": media_type}
    if url:
        block["url"] = url
    if data:
        block["data"] = data
    return block


def thinking_block(text: str) -> ContentBlock:
    return {"type": "thinking", "text": text}


# ---------------------------------------------------------------------------
# Msg
# ---------------------------------------------------------------------------


class Msg:
    """A conversation message with structured content blocks.

    要点：
      * url / audio 等细分字段统一塞进 blocks，不单独放 Msg 属性。
      * ``metadata`` 留作扩展字段（如 ``session_entry_type``、压缩标记等）。
      * 内容永远是 ``list[ContentBlock]``；纯字符串构造时会自动包成 text block。
    """

    __slots__ = ("id", "role", "name", "blocks", "metadata", "timestamp")

    def __init__(
        self,
        role: MsgRole | str,
        content: str | Iterable[ContentBlock] | None = None,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        msg_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        if not isinstance(role, MsgRole):
            role = MsgRole(role)
        self.role: MsgRole = role
        self.name = name or role.value
        self.metadata: dict[str, Any] = dict(metadata or {})
        self.id = msg_id or uuid.uuid4().hex
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

        if content is None:
            self.blocks: list[ContentBlock] = []
        elif isinstance(content, str):
            self.blocks = [text_block(content)] if content else []
        else:
            self.blocks = [_normalize_block(b) for b in content]

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def user(cls, text: str, *, name: str | None = None) -> Msg:
        return cls(MsgRole.USER, text, name=name or "user")

    @classmethod
    def assistant(
        cls,
        blocks: Iterable[ContentBlock] | str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Msg:
        return cls(MsgRole.ASSISTANT, blocks, name=name or "assistant", metadata=metadata)

    @classmethod
    def system(cls, text: str, *, name: str | None = None) -> Msg:
        return cls(MsgRole.SYSTEM, text, name=name or "system")

    @classmethod
    def tool_results(
        cls,
        results: Iterable[ContentBlock],
        *,
        name: str | None = None,
    ) -> Msg:
        """A SYSTEM-role message carrying one or more tool_result blocks.

        工具结果观察值统一挂在 "system" role 消息上（而不是 "tool"），下游 OpenAI
        formatter 再把它们拆成 ``role="tool"`` 的 API 条目。
        """
        return cls(MsgRole.SYSTEM, list(results), name=name or "system")

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    def get_text_content(self) -> str:
        parts: list[str] = []
        for b in self.blocks:
            t = b.get("type")
            if t == "text" and b.get("text"):
                parts.append(str(b["text"]))
        return "\n".join(parts)

    def get_content_blocks(self, block_type: str | None = None) -> list[ContentBlock]:
        if block_type is None:
            return list(self.blocks)
        return [b for b in self.blocks if b.get("type") == block_type]

    @property
    def content(self) -> list[ContentBlock]:
        """``msg.content`` alias for ``msg.blocks`` (kept for historical call sites)."""
        return self.blocks

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role.value,
            "content": [dict(b) for b in self.blocks],
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Msg:
        if not isinstance(data, dict):
            raise TypeError(f"Msg.from_dict expects dict, got {type(data).__name__}")
        role = data.get("role") or "user"
        raw_content = data.get("content")
        if isinstance(raw_content, str):
            blocks: list[ContentBlock] = [text_block(raw_content)] if raw_content else []
        elif isinstance(raw_content, list):
            blocks = [_normalize_block(b) for b in raw_content if b is not None]
        else:
            blocks = []
        return cls(
            role=role,
            content=blocks,
            name=data.get("name"),
            metadata=data.get("metadata") or {},
            msg_id=data.get("id"),
            timestamp=data.get("timestamp"),
        )


# ---------------------------------------------------------------------------
# Block normalisation
# ---------------------------------------------------------------------------


_VALID_BLOCK_TYPES = {"text", "tool_use", "tool_result", "image", "thinking", "audio", "video"}


def _normalize_block(block: Any) -> ContentBlock:
    """Coerce a raw dict from any historical source into our block schema."""
    if not isinstance(block, dict):
        return text_block(str(block))
    t = block.get("type")
    if t == "text":
        return {"type": "text", "text": str(block.get("text") or "")}
    if t == "tool_use":
        raw_input = block.get("input")
        if isinstance(raw_input, str):
            try:
                import json

                raw_input = json.loads(raw_input) if raw_input else {}
            except Exception:
                raw_input = {"_raw": raw_input}
        return {
            "type": "tool_use",
            "id": str(block.get("id") or ""),
            "name": str(block.get("name") or ""),
            "input": raw_input or {},
        }
    if t == "tool_result":
        out: dict[str, Any] = {
            "type": "tool_result",
            "id": str(block.get("id") or ""),
            "name": str(block.get("name") or ""),
            "output": block.get("output"),
        }
        if block.get("is_error"):
            out["is_error"] = True
        return out
    if t == "image":
        out = {"type": "image", "media_type": block.get("media_type") or "image/png"}
        if block.get("url"):
            out["url"] = block["url"]
        if block.get("data"):
            out["data"] = block["data"]
        return out
    if t == "thinking":
        return {"type": "thinking", "text": str(block.get("text") or "")}
    if t in _VALID_BLOCK_TYPES:
        return dict(block)
    # Unknown type — degrade to text representation to avoid losing data.
    return text_block(str(block))


__all__ = [
    "ContentBlock",
    "Msg",
    "MsgRole",
    "text_block",
    "tool_use_block",
    "tool_result_block",
    "image_block",
    "thinking_block",
]
