"""Agent 钩子 — 审计日志。

通过 ``app.runtime_core.hooks.HookRunner`` 注入 ``ConversationRuntime``
的关键阶段（pre_reply / post_reply / pre_acting / post_acting），不修改
runtime 核心代码。

公开入口：
  - register_audit_hooks(runner)
"""

from __future__ import annotations

import logging
from typing import Any

from app.runtime_core.hooks import HookRunner, HookStage
from app.runtime_core.messages import Msg, MsgRole

logger = logging.getLogger("agent_hooks")

_MAX_LOG_LEN = 200


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _runtime_name(payload: dict[str, Any]) -> str:
    runtime = payload.get("runtime")
    name = getattr(runtime, "name", None)
    if isinstance(name, str) and name:
        return name
    msg = payload.get("msg")
    n = getattr(msg, "name", None)
    if isinstance(n, str) and n:
        return n
    return "agent"


def _summarize(value: Any) -> str:
    if value is None:
        return "<none>"
    if isinstance(value, Msg):
        text = value.get_text_content()
        if text:
            return repr(text[:_MAX_LOG_LEN])
    text = str(value)
    if len(text) > _MAX_LOG_LEN:
        return text[:_MAX_LOG_LEN] + "..."
    return text


def _last_user_msg(runtime: Any) -> Msg | None:
    """Return the last USER-role message currently in memory."""
    if runtime is None:
        return None
    memory = getattr(runtime, "memory", None)
    if memory is None:
        return None
    try:
        msgs = memory.get_memory()
    except Exception:
        return None
    for m in reversed(msgs):
        if isinstance(m, Msg) and m.role == MsgRole.USER:
            return m
    return None


# ------------------------------------------------------------------
# Audit hook fns (HookRunner-style: async (payload) -> dict | None)
# ------------------------------------------------------------------


async def _audit_pre_reply(payload: dict[str, Any]) -> dict[str, Any] | None:
    runtime = payload.get("runtime")
    user_msg = _last_user_msg(runtime)
    logger.info("[%s] pre_reply: input=%s", _runtime_name(payload), _summarize(user_msg))
    return None


async def _audit_post_reply(payload: dict[str, Any]) -> dict[str, Any] | None:
    msg = payload.get("msg")
    logger.info("[%s] post_reply: output=%s", _runtime_name(payload), _summarize(msg))
    return None


async def _audit_pre_acting(payload: dict[str, Any]) -> dict[str, Any] | None:
    logger.info(
        "[%s] pre_acting: tool=%s args=%s",
        _runtime_name(payload),
        payload.get("tool_name"),
        _summarize(payload.get("arguments")),
    )
    return None


async def _audit_post_acting(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = payload.get("result")
    is_error = bool(getattr(result, "is_error", False))
    output = getattr(result, "output", result)
    logger.info(
        "[%s] post_acting: tool=%s is_error=%s result=%s",
        _runtime_name(payload),
        payload.get("tool_name"),
        is_error,
        _summarize(output),
    )
    return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def register_audit_hooks(runner: HookRunner) -> None:
    """为给定 HookRunner 注册全套审计钩子。"""
    runner.register(HookStage.PRE_REPLY, "audit_pre_reply", _audit_pre_reply)
    runner.register(HookStage.POST_REPLY, "audit_post_reply", _audit_post_reply)
    runner.register(HookStage.PRE_ACTING, "audit_pre_acting", _audit_pre_acting)
    runner.register(HookStage.POST_ACTING, "audit_post_acting", _audit_post_acting)
