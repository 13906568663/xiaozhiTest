"""工具调用日志埋点。

提供 :func:`make_tool_call_logger_hook` 工厂函数，返回符合 ``HookFn`` 协议
的 POST_ACTING hook。挂载后每次工具调用结束会同步写一条 ``tool_call_log``
记录，用于支撑外部 API 调用统计接口。

设计要点：
  * **独立 session**：用 ``SessionLocal()`` 起独立短事务写入，避免与主链路
    业务事务耦合；写失败只打 warning，绝不影响业务主流程。
  * **敏感字段 mask**：``arguments_json`` 中匹配 ``_SENSITIVE_KEY_PATTERNS``
    的 key 会递归替换为 ``"***"``；防止把 token / password 等凭证落库。
  * **大 payload 截断**：``response_preview`` 截到配置的字符数；
    ``arguments_json`` 序列化后超过上限会整体置换为 ``{"_truncated": true}``，
    避免单条日志撑爆表。
  * **可关闭**：通过 ``settings.tool_call_log_enabled`` 开关一键停写。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings
from app.db.models.chatbot import ToolCallLog
from app.db.session import SessionLocal
from app.runtime_core.hooks import HookFn
from app.runtime_core.tool_protocol import ToolCategory, ToolContext, ToolResult
from app.workflow.runtime.http_invoker import HTTP_META_KEY

logger = logging.getLogger(__name__)


# 敏感字段名（小写匹配）。任一 key 包含以下子串就被认为是敏感字段。
_SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "credential",
)


def _mask_sensitive(value: Any) -> Any:
    """递归遍历 dict / list，把敏感字段的值替换为 ``"***"``。"""
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for k, v in value.items():
            key_lower = str(k).lower()
            if any(pat in key_lower for pat in _SENSITIVE_KEY_PATTERNS):
                masked[str(k)] = "***"
            else:
                masked[str(k)] = _mask_sensitive(v)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive(item) for item in value]
    return value


def _truncate_str(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _safe_arguments_json(arguments: Any, max_chars: int) -> dict[str, Any]:
    """把 arguments 转成可序列化的 dict，并做敏感字段 mask + 整体截断。

    若 arguments 非 dict 或序列化失败，统一兜底成
    ``{"_value": "<repr>"}`` / ``{"_truncated": true}``。
    """
    if not isinstance(arguments, dict):
        return {"_value": repr(arguments)[:max_chars]}
    masked = _mask_sensitive(arguments)
    try:
        serialized = json.dumps(masked, ensure_ascii=False, default=str)
    except Exception:
        return {"_serialize_failed": True}
    if len(serialized) > max_chars:
        return {"_truncated": True, "_size": len(serialized)}
    if isinstance(masked, dict):
        return masked
    return {"_value": masked}


def _extract_error_message(
    tool_result: ToolResult | None, max_chars: int
) -> str | None:
    if tool_result is None or not tool_result.is_error:
        return None
    output = tool_result.output
    if isinstance(output, dict):
        msg = output.get("error") or output.get("error_message")
        if msg:
            return _truncate_str(str(msg), max_chars)
    text = tool_result.output_text()
    return _truncate_str(text, max_chars) if text else None


def _extract_http_meta(tool_result: ToolResult | None) -> dict[str, Any]:
    """从 ToolResult.metadata 抽出 _http_meta；找不到返回空 dict。"""
    if tool_result is None:
        return {}
    meta = tool_result.metadata.get(HTTP_META_KEY)
    if isinstance(meta, dict):
        return meta
    return {}


def make_tool_call_logger_hook() -> HookFn:
    """构造一个 POST_ACTING hook，把工具调用元数据落库到 ``tool_call_log``。

    Returns:
        符合 ``HookFn`` 签名的异步函数。注册示例：

        >>> hook_runner.register(
        ...     HookStage.POST_ACTING, "tool_call_logger",
        ...     make_tool_call_logger_hook(),
        ... )

    Hook 不修改 payload；返回 ``None`` 让 HookRunner 走默认放行分支。
    """

    settings = get_settings()
    args_max = settings.tool_call_log_arguments_max_chars
    response_max = settings.tool_call_log_response_preview_max_chars
    error_max = settings.tool_call_log_error_message_max_chars

    async def _hook(payload: dict) -> dict | None:
        if not settings.tool_call_log_enabled:
            return None

        ctx = payload.get("context")
        if not isinstance(ctx, ToolContext) or not ctx.session_id:
            return None

        tool_name = str(payload.get("tool_name") or "").strip()
        if not tool_name:
            return None

        category_val = payload.get("category")
        if isinstance(category_val, ToolCategory):
            category_str = category_val.value
        else:
            category_str = str(category_val or ToolCategory.META.value)

        tool_result = payload.get("result")
        if not isinstance(tool_result, ToolResult):
            tool_result = None

        http_meta = _extract_http_meta(tool_result)
        http_method = http_meta.get("method")
        http_status_code = http_meta.get("status_code")
        # duration_ms 优先取 runtime 测得的整体执行耗时；HTTP 类目同时也有
        # _http_meta.duration_ms（仅 HTTP 请求本身），两者通常相差不大，runtime
        # 这个更全面（含 wrapper 序列化），所以优先用 runtime 测的值。
        duration_ms = payload.get("duration_ms")
        if not isinstance(duration_ms, int):
            duration_ms = int(http_meta.get("duration_ms") or 0)

        is_success = not bool(getattr(tool_result, "is_error", False))
        error_message = _extract_error_message(tool_result, error_max)
        arguments_json = _safe_arguments_json(payload.get("arguments"), args_max)

        response_preview: str | None = None
        if tool_result is not None:
            try:
                response_preview = _truncate_str(
                    tool_result.output_text(), response_max
                )
            except Exception:
                response_preview = None

        try:
            async with SessionLocal() as db:
                db.add(
                    ToolCallLog(
                        session_id=str(ctx.session_id),
                        tool_name=tool_name[:255],
                        tool_category=category_str[:32],
                        http_method=(str(http_method)[:8] if http_method else None),
                        http_status_code=(
                            int(http_status_code)
                            if isinstance(http_status_code, int)
                            else None
                        ),
                        duration_ms=max(0, int(duration_ms or 0)),
                        is_success=is_success,
                        error_message=error_message,
                        arguments_json=arguments_json,
                        response_preview=response_preview,
                    )
                )
                await db.commit()
        except Exception:
            # 写日志失败兜底：只 warning，绝不向上抛，避免影响业务主流程
            logger.warning(
                "tool_call_logger write failed for tool=%s session=%s",
                tool_name,
                ctx.session_id,
                exc_info=True,
            )
        return None

    return _hook


__all__ = ["make_tool_call_logger_hook"]
