"""Chatbot 内置工具集合。

注册不依赖外部 HTTP / MCP / 知识库的"原生"工具，所有 chatbot 默认都拥有。

目前包含：
  * ``get_current_time``：返回助手运行时的墙钟时间（默认 Asia/Shanghai），
    供 LLM 把"今晚 / 最近 2 天 / 上周三"等相对时间换算成绝对时间窗。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.runtime_core.tool_protocol import (
    ToolCategory,
    ToolRegistry,
    ToolResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_TZ = "Asia/Shanghai"
_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register chatbot-level builtin tools.

    Currently registers:
      * ``get_current_time``: wall-clock time in a target timezone.
    """
    registry.register_function(
        name="get_current_time",
        description=(
            "Return the current wall-clock time. Default timezone is Asia/Shanghai. "
            "Use this to resolve relative time phrases like '今晚', '最近 2 天', "
            "'上周三' into absolute timestamps before querying downstream APIs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tz": {
                    "type": "string",
                    "description": (
                        "IANA timezone name, e.g. 'Asia/Shanghai' (default), 'UTC', "
                        "'Asia/Tokyo'. Unknown values fall back to Asia/Shanghai."
                    ),
                },
            },
            "additionalProperties": False,
        },
        fn=_get_current_time,
        category=ToolCategory.META,
        is_read_only=True,
        parallel_safe=True,
    )


async def _get_current_time(**kwargs: Any) -> ToolResult:
    tz_name = str(kwargs.get("tz") or _DEFAULT_TZ).strip() or _DEFAULT_TZ
    used_tz_name = tz_name
    tz_fallback = False
    try:
        local_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning(
            "get_current_time: unknown timezone %r, falling back to %s",
            tz_name,
            _DEFAULT_TZ,
        )
        local_tz = ZoneInfo(_DEFAULT_TZ)
        used_tz_name = _DEFAULT_TZ
        tz_fallback = True

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(local_tz)

    payload: dict[str, Any] = {
        "success": True,
        "tool_name": "get_current_time",
        "iso_local": now_local.isoformat(timespec="seconds"),
        "iso_utc": now_utc.isoformat(timespec="seconds"),
        "human_local": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "date_local": now_local.strftime("%Y-%m-%d"),
        "weekday": _WEEKDAY_ZH[now_local.weekday()],
        "timezone": used_tz_name,
        "unix_timestamp": int(now_utc.timestamp()),
    }
    if tz_fallback:
        payload["note"] = (
            f"Unknown timezone '{tz_name}', fell back to {_DEFAULT_TZ}."
        )

    return ToolResult(output=payload, metadata=payload)


__all__ = ["register_builtin_tools"]
