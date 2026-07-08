"""运行时共享的小型工具函数。"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

_REASONING_EFFORTS = ("low", "medium", "high")
_MCP_TRANSPORTS = ("streamable_http", "sse")
_SUPPORTED_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
DEFAULT_MEMORY_COMPRESSION_THRESHOLD = 32000
DEFAULT_AGENT_EXECUTION_TIMEOUT_SECONDS = 300


def snapshot_json(value: Any) -> Any:
    """把任意值收敛成可 JSON 序列化的纯 Python 结构。"""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def coerce_str_dict(value: Any) -> dict[str, str] | None:
    """把任意 dict 尽量转成 str->str，用于 headers/env 等场景。"""
    if not isinstance(value, dict):
        return None
    return {str(key): str(item) for key, item in value.items()}


def coerce_reasoning_effort(raw: Any) -> Literal["low", "medium", "high"] | None:
    """将配置值收敛到我们当前支持的 reasoning effort 枚举。"""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in _REASONING_EFFORTS:
        return cast(Literal["low", "medium", "high"], s)
    return None


def coerce_memory_compression_threshold(raw: Any) -> int:
    """归一化 Agent 记忆压缩触发阈值。"""
    if raw is None:
        return DEFAULT_MEMORY_COMPRESSION_THRESHOLD
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_MEMORY_COMPRESSION_THRESHOLD
    return value if value > 0 else DEFAULT_MEMORY_COMPRESSION_THRESHOLD


def coerce_agent_execution_timeout_seconds(raw: Any) -> int:
    """归一化 Agent 单轮执行总超时。"""
    if raw is None:
        return DEFAULT_AGENT_EXECUTION_TIMEOUT_SECONDS
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_AGENT_EXECUTION_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_AGENT_EXECUTION_TIMEOUT_SECONDS


def coerce_mcp_transport(raw: Any) -> Literal["streamable_http", "sse"]:
    """归一化 MCP transport，避免配置缺失或大小写差异导致运行时报错。"""
    s = str(raw or "streamable_http").strip().lower()
    if s in _MCP_TRANSPORTS:
        return cast(Literal["streamable_http", "sse"], s)
    return "streamable_http"


def coerce_http_method(raw: Any) -> Literal["GET", "POST", "PUT", "PATCH", "DELETE"]:
    """把 HTTP method 规范成受支持的大写枚举。"""
    method = str(raw or "POST").strip().upper()
    if method in _SUPPORTED_HTTP_METHODS:
        return cast(Literal["GET", "POST", "PUT", "PATCH", "DELETE"], method)
    return "POST"
