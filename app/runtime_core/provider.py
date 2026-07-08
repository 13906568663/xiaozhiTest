"""Async OpenAI-compatible chat completions provider (httpx based).

Features
~~~~~~~~
* ``stream_chat``：异步流式生成器，按 chunk 产出 text/tool_call/usage/error/thinking。
* ``simple_chat``：一次性 chat completion，用于"压缩总结"等无需流的场景。
* 自动 max_tokens 截断重试。
* 自动 input+output 超总长度（context window 溢出）重试：把 max_tokens 缩
  到 ``context_length - passed_input - buffer`` 再试一次。
* DeepSeek/通义/智谱等兼容供应商：URL 由 ``base_url + /chat/completions`` 拼接。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """LLM API 调用的 token 用量累计器。

    provider 的 ``stream_chat`` 会在流末尾产出一条 ``{"type": "usage", ...}``
    chunk（来自 ``stream_options.include_usage``），runtime 消费后累计到本结构。
    ``requests`` 由 runtime 在每次发起 LLM 调用时显式 +1（不依赖 usage chunk，
    部分网关不回报 usage 时请求数仍准确）。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    requests: int = 0

    def record(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens += max(0, int(input_tokens or 0))
        self.output_tokens += max(0, int(output_tokens or 0))
        self.cache_read_input_tokens += max(0, int(cache_read_input_tokens or 0))

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "requests": self.requests,
        }


_MAX_TOKENS_RANGE_RE = re.compile(
    r"max_tokens.*?\[\s*\d+\s*,\s*(\d+)\s*\]",
    re.IGNORECASE,
)

# 兼容多种"上下文窗口溢出"错误文案——主要是国内 OpenAI 兼容网关（DashScope /
# Moonshot / Anthropic 风格等）的 BadRequestError。
_PASSED_INPUT_TOKENS_RE = re.compile(
    r"passed\s+(\d+)\s+input\s+tokens", re.IGNORECASE,
)
_CONTEXT_LENGTH_RE = re.compile(
    r"context\s+length\s+(?:is\s+only\s+|of\s+|is\s+)?(\d+)\s*tokens?",
    re.IGNORECASE,
)
_MAX_INPUT_LENGTH_RE = re.compile(
    r"maximum\s+input\s+length\s+of\s+(\d+)\s*tokens?", re.IGNORECASE,
)

# 重试时给 max_tokens 留的最小输出额度：低于这个值再继续没意义，直接放弃，让
# 上层走"上下文已超限"的提示流程。
_MIN_RETRY_MAX_TOKENS = 256
# 收缩 max_tokens 时留一点 buffer，避免 token 估算误差再次踩线。
_OVERFLOW_RETRY_BUFFER_TOKENS = 64


def _extract_max_tokens_upper_bound(error_text: str) -> int | None:
    match = _MAX_TOKENS_RANGE_RE.search(error_text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _compute_context_overflow_retry_max_tokens(
    error_text: str,
    current_max_tokens: int,
) -> int | None:
    """识别"input+output 超 context"类 400 错误，计算可重试的新 max_tokens。

    场景（典型错误文案）::

        You passed 124809 input tokens and requested 8192 output tokens.
        However, the model's context length is only 133000 tokens,
        resulting in a maximum input length of 124808 tokens.

    返回：
      * ``int``  → 可以重试，返回新的 ``max_tokens``；
      * ``None`` → 无法识别 / 无法通过缩 max_tokens 救回（input 本身已超 context）；
        上层应直接把错误透传给用户。
    """
    if not error_text:
        return None
    passed_match = _PASSED_INPUT_TOKENS_RE.search(error_text)
    if not passed_match:
        return None
    try:
        passed_input = int(passed_match.group(1))
    except ValueError:
        return None

    context_length: int | None = None
    ctx_match = _CONTEXT_LENGTH_RE.search(error_text)
    if ctx_match:
        try:
            context_length = int(ctx_match.group(1))
        except ValueError:
            context_length = None
    if context_length is None:
        # 兜底：网关偶尔只给"max input length"，没给总 context；
        # 那就把 max input length 当作"能塞下的 input 上限"——再缩输出就只能
        # 让 max_tokens 比当前小一点，意义不大；视为无法救回。
        max_in_match = _MAX_INPUT_LENGTH_RE.search(error_text)
        if not max_in_match:
            return None
        try:
            max_input_length = int(max_in_match.group(1))
        except ValueError:
            return None
        if passed_input > max_input_length:
            # input 自身已经超过了"输出留 0 的最大输入"上限——靠缩 max_tokens
            # 救不回来，只能让上层去压缩历史。
            return None
        return None

    # context_length 可用：算"还能给输出多少空间"
    budget_for_output = context_length - passed_input - _OVERFLOW_RETRY_BUFFER_TOKENS
    if budget_for_output < _MIN_RETRY_MAX_TOKENS:
        # input 实际上已经把 context 吃光：再小的 max_tokens 也救不回来。
        return None
    new_max_tokens = min(int(current_max_tokens or 0) or budget_for_output, budget_for_output)
    if new_max_tokens >= int(current_max_tokens or 0):
        # 没法变得更小（说明 current 已经小到刚好等于 budget），重试无意义。
        return None
    return max(_MIN_RETRY_MAX_TOKENS, new_max_tokens)


class OpenAICompatProvider:
    """Async chat-completions client for any OpenAI-compatible API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        max_tokens: int = 4096,
        stream: bool = True,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
        auth_header_name: str = "Authorization",
        auth_header_scheme: str = "Bearer ",
        timeout: float = 300.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for OpenAICompatProvider")
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.max_tokens = int(max_tokens or 1024)
        self.stream = stream
        self.reasoning_effort = reasoning_effort
        self.extra_body = dict(extra_body or {})
        # 自定义鉴权头：网关接入场景常见 'Authorization-Gateway: sk-xxx' 这类格式，
        # 需要既能改 header 名又能去掉 'Bearer ' 前缀。
        self.auth_header_name = (auth_header_name or "Authorization").strip() or "Authorization"
        self.auth_header_scheme = auth_header_scheme if auth_header_scheme is not None else "Bearer "
        self.timeout = timeout
        # 一个 provider 实例对应一份 model 配置，HTTP 客户端复用。
        self._client = httpx.AsyncClient(timeout=timeout)
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._client.aclose()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Streaming chat
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion. Yields dicts with type=
        ``text_delta``/``thinking_delta``/``tool_call``/``usage``/``error``."""
        body, headers, url = self._build_request(messages, tools=tools, stream=True)

        attempt = 0
        # 两类自适应重试各最多一次：max_tokens 超 provider cap、input+output 超
        # context window。两类都中也最多再多吃一轮，不会无限重试。
        max_attempts = 3

        while True:
            attempt += 1
            try:
                async with self._client.stream(
                    "POST", url, json=body, headers=headers
                ) as response:
                    if response.status_code != 200:
                        err_text = (await response.aread()).decode(errors="replace")
                        upper = _extract_max_tokens_upper_bound(err_text)
                        if (
                            upper is not None
                            and upper > 0
                            and body.get("max_tokens", 0) > upper
                            and attempt < max_attempts
                        ):
                            logger.warning(
                                "max_tokens=%s exceeds provider cap %s; retrying.",
                                body.get("max_tokens"), upper,
                            )
                            body["max_tokens"] = upper
                            self.max_tokens = upper
                            continue
                        # context window 溢出：input + 要求的 output > context
                        # length。这类错误在国内 OpenAI 兼容网关上很常见，比如
                        # Anthropic 风格的 BadRequestError("You passed N input
                        # tokens and requested M output tokens. However, the
                        # model's context length is only C tokens...")。
                        # 把 max_tokens 缩到剩余 budget 再试一次。
                        new_max_tokens = _compute_context_overflow_retry_max_tokens(
                            err_text, body.get("max_tokens", 0),
                        )
                        if new_max_tokens is not None and attempt < max_attempts:
                            logger.warning(
                                "context overflow: shrinking max_tokens %s -> %s "
                                "and retrying (model=%s)",
                                body.get("max_tokens"), new_max_tokens, self.model,
                            )
                            body["max_tokens"] = new_max_tokens
                            self.max_tokens = new_max_tokens
                            continue
                        logger.error(
                            "Chat API %d for model=%s: %s",
                            response.status_code, self.model, err_text[:1000],
                        )
                        yield {
                            "type": "error",
                            "message": f"API {response.status_code}: {err_text[:500]}",
                        }
                        return

                    async for event in self._iter_stream(response):
                        yield event
                return
            except httpx.HTTPError as exc:
                yield {"type": "error", "message": f"HTTP error: {exc}"}
                return

    async def _iter_stream(
        self, response: httpx.Response,
    ) -> AsyncIterator[dict[str, Any]]:
        """Parse an OpenAI SSE stream into normalised events."""
        pending_tool_calls: dict[int, dict[str, Any]] = {}

        async for line in response.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            usage = chunk.get("usage")
            if usage:
                prompt_details = usage.get("prompt_tokens_details") or {}
                yield {
                    "type": "usage",
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "cache_read_input_tokens": (
                        prompt_details.get("cached_tokens")
                        or usage.get("cache_read_input_tokens", 0)
                    ),
                }

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}

            if content := delta.get("content"):
                yield {"type": "text_delta", "content": content}

            if reasoning := delta.get("reasoning_content"):
                yield {"type": "thinking_delta", "content": reasoning}

            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = pending_tool_calls.setdefault(
                    idx, {"id": "", "name": "", "arguments": ""}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]

            finish_reason = choices[0].get("finish_reason")
            if finish_reason in ("tool_calls", "stop", "length") and pending_tool_calls:
                for slot in pending_tool_calls.values():
                    if slot["name"]:
                        yield {
                            "type": "tool_call",
                            "id": slot["id"] or _fake_call_id(),
                            "name": slot["name"],
                            "arguments": slot["arguments"] or "{}",
                        }
                pending_tool_calls.clear()

    # ------------------------------------------------------------------
    # Non-streaming chat (used by compaction)
    # ------------------------------------------------------------------

    async def simple_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        body, headers, url = self._build_request(messages, tools=None, stream=False)
        body["max_tokens"] = int(max_tokens or 1024)
        if response_format is not None:
            body["response_format"] = response_format

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await self._client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("simple_chat HTTP error: %s", exc)
                return ""

            if resp.status_code == 400 and response_format is not None and attempt == 1:
                # Fallback: drop response_format and retry once.
                body.pop("response_format", None)
                continue

            if resp.status_code != 200:
                err_text = resp.text or ""
                upper = _extract_max_tokens_upper_bound(err_text)
                if (
                    upper is not None
                    and upper > 0
                    and body.get("max_tokens", 0) > upper
                    and attempt < 3
                ):
                    body["max_tokens"] = upper
                    continue
                # 同 stream_chat：input+output 超 context 时缩 max_tokens 重试。
                new_max_tokens = _compute_context_overflow_retry_max_tokens(
                    err_text, body.get("max_tokens", 0),
                )
                if new_max_tokens is not None and attempt < 3:
                    logger.warning(
                        "simple_chat context overflow: shrinking max_tokens "
                        "%s -> %s and retrying (model=%s)",
                        body.get("max_tokens"), new_max_tokens, self.model,
                    )
                    body["max_tokens"] = new_max_tokens
                    continue
                logger.warning("simple_chat %d: %s", resp.status_code, err_text[:300])
                return ""

            try:
                data = resp.json()
            except Exception:
                return ""
            choices = data.get("choices") or []
            if not choices:
                return ""
            return (choices[0].get("message") or {}).get("content") or ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> tuple[dict[str, Any], dict[str, str], str]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
            # 显式打开并行 tool_calls：相邻的几个轻量工具调用（典型场景是
            # plan_update_subtask 标 done + 标下一个 in_progress）放在一次
            # assistant 响应里发出，能省掉一整轮 LLM round-trip。
            # OpenAI 协议默认就是 true，但部分国内兼容供应商在没显式收到
            # 这个字段时会按"串行"实现，所以这里一律显式发。
            body["parallel_tool_calls"] = True
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            body.update(self.extra_body)

        headers = {
            "Content-Type": "application/json",
            self.auth_header_name: f"{self.auth_header_scheme}{self.api_key}",
        }
        url = f"{self.base_url}/chat/completions"
        return body, headers, url


def _fake_call_id() -> str:
    import uuid

    return f"call_{uuid.uuid4().hex[:24]}"


__all__ = ["OpenAICompatProvider", "TokenUsage"]
