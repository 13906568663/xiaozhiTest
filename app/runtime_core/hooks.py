"""Lightweight runtime hooks.

提供 ``HookRunner`` 让外部在 ConversationRuntime 的关键阶段插桩：
  * pre_reply / post_reply: 整轮 reply 入口与出口（用于审计、敏感词拦截）
  * pre_reasoning / post_reasoning: 一次 LLM 调用前后
  * pre_acting / post_acting: 工具调用前后

调用约定：
  * Hook 函数签名 ``async def(payload: dict) -> dict | None``
  * 返回 ``None`` 表示放行，原 payload 不变
  * 返回 ``dict``：浅合并 payload 后继续；可写入 ``"_blocked": True`` 让
    runtime 中止当前阶段（pre_reply / pre_acting 阶段生效，详见 runtime）
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from enum import Enum

logger = logging.getLogger(__name__)


HookFn = Callable[[dict], Awaitable[dict | None]]


class HookStage(str, Enum):
    PRE_REPLY = "pre_reply"
    POST_REPLY = "post_reply"
    PRE_REASONING = "pre_reasoning"
    POST_REASONING = "post_reasoning"
    PRE_ACTING = "pre_acting"
    POST_ACTING = "post_acting"


class HookRunner:
    def __init__(self) -> None:
        self._hooks: dict[HookStage, list[tuple[str, HookFn]]] = {
            stage: [] for stage in HookStage
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, stage: HookStage, name: str, fn: HookFn) -> None:
        self._hooks[stage].append((name, fn))

    def unregister(self, stage: HookStage, name: str) -> None:
        self._hooks[stage] = [(n, fn) for (n, fn) in self._hooks[stage] if n != name]

    def has_hooks(self, stage: HookStage) -> bool:
        return bool(self._hooks[stage])

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, stage: HookStage, payload: dict) -> dict:
        if not self._hooks[stage]:
            return payload
        merged = dict(payload)
        for name, fn in self._hooks[stage]:
            try:
                ret = await fn(merged)
            except Exception:
                logger.exception("Hook %s/%s raised; ignoring", stage.value, name)
                continue
            if isinstance(ret, dict):
                merged.update(ret)
                if merged.get("_blocked"):
                    merged.setdefault("_blocked_by", name)
                    return merged
        return merged


__all__ = ["HookFn", "HookRunner", "HookStage"]
