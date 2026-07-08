"""Python 节点运行时：用纯 Python callable 取代 LLM 推理。

适用场景：节点的工作本质上是「按确定规则把上游数据拼装成下游数据 / 文件」，
让 LLM 来做只会引入额外的 token 成本与漏调 generate_response 的风险。

handler 协议
-------------

handler 是一个 async callable，import 路径在 ``node.python_handler`` 中配置，
格式 ``module.sub:func`` 或 ``module.sub.func``。

签名::

    async def handler(
        context: dict[str, Any],
        *,
        db_session: AsyncSession,
        runtime_context: dict[str, Any],
        handler_config: dict[str, Any],
        node: TaskNodeDefinition,
    ) -> dict[str, Any]: ...

* ``context`` 是 ``task_run.context_json``（**含 artifact ref 形态**，handler
  需要 raw 数据时显式调 :func:`resolve_artifact_refs` 展开）。
* ``handler_config`` 来自 ``node.python_handler_config``，传递批大小 / 超时
  /降级开关等。
* 返回的 dict 等同于 AGENT 节点 ``generate_response(action=complete, result=...)``
  里的 ``result``，会被引擎写入 ``context[node.code]``。

异常 → ``SessionTurnAction.FAIL``，前端能直接看到错误信息。
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
import traceback
from typing import Any

from app.workflow.runtime.helpers import snapshot_json
from app.workflow.runtime.types import (
    SessionTurnAction,
    SessionTurnResult,
)
from app.workflow.schemas import TaskNodeDefinition

logger = logging.getLogger(__name__)

# Python handler 默认超时（秒）。多数 handler 应在数秒内完成；超过此值通常
# 意味着外部接口卡死（如资管 OAuth 或 fiberSTAR 抖动），允许通过
# ``handler_config.timeout_seconds`` 覆盖。
DEFAULT_PYTHON_HANDLER_TIMEOUT_SECONDS = 300


class PythonNodeRuntime:
    """与 NodeRuntime 对偶的 Python 节点执行器。"""

    async def run_python_handler(
        self,
        node: TaskNodeDefinition,
        context: dict[str, Any],
        *,
        runtime_state: dict[str, Any] | None = None,
        sleep_checkpoint: dict[str, Any] | None = None,
        compensation_config: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
        db_session: Any | None = None,
        event_publisher: Any | None = None,
    ) -> SessionTurnResult:
        """加载并执行 ``node.python_handler``，封装成 ``SessionTurnResult``。"""
        handler_ref = (node.python_handler or "").strip()
        if not handler_ref:
            return self._fail(
                node,
                error_message=(
                    f"Python 节点 {node.code} 未配置 python_handler。请在节点 "
                    f"config_json 中提供 'app.module:func' 形式的 handler。"
                ),
                runtime_state=runtime_state,
                sleep_checkpoint=sleep_checkpoint,
                compensation_config=compensation_config,
            )

        try:
            handler = self._import_handler(handler_ref)
        except Exception as exc:
            return self._fail(
                node,
                error_message=(
                    f"Python 节点 {node.code} 加载 handler {handler_ref!r} 失败：{exc}"
                ),
                runtime_state=runtime_state,
                sleep_checkpoint=sleep_checkpoint,
                compensation_config=compensation_config,
            )

        timeout_seconds = float(
            (node.python_handler_config or {}).get("timeout_seconds")
            or DEFAULT_PYTHON_HANDLER_TIMEOUT_SECONDS
        )
        start = time.perf_counter()
        try:
            result_payload = await asyncio.wait_for(
                handler(
                    context,
                    db_session=db_session,
                    runtime_context=runtime_context or {},
                    handler_config=dict(node.python_handler_config or {}),
                    node=node,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start
            logger.error(
                "[%s] Python handler %s timed out after %.2fs (limit=%ss).",
                node.code, handler_ref, elapsed, timeout_seconds,
            )
            return self._fail(
                node,
                error_message=(
                    f"Python 节点 {node.code} handler {handler_ref!r} "
                    f"执行超时 {timeout_seconds}s。"
                ),
                runtime_state=runtime_state,
                sleep_checkpoint=sleep_checkpoint,
                compensation_config=compensation_config,
            )
        except Exception as exc:
            logger.exception(
                "[%s] Python handler %s raised.", node.code, handler_ref,
            )
            return self._fail(
                node,
                error_message=(
                    f"Python 节点 {node.code} handler {handler_ref!r} 抛出异常："
                    f"{type(exc).__name__}: {exc}"
                ),
                runtime_state=runtime_state,
                sleep_checkpoint=sleep_checkpoint,
                compensation_config=compensation_config,
                detail={"traceback": traceback.format_exc()[-2000:]},
            )

        elapsed = time.perf_counter() - start
        logger.info(
            "[%s] Python handler %s finished in %.2fs.",
            node.code, handler_ref, elapsed,
        )

        if not isinstance(result_payload, dict):
            return self._fail(
                node,
                error_message=(
                    f"Python 节点 {node.code} handler 返回类型必须是 dict，"
                    f"实际为 {type(result_payload).__name__}。"
                ),
                runtime_state=runtime_state,
                sleep_checkpoint=sleep_checkpoint,
                compensation_config=compensation_config,
            )

        output = snapshot_json(result_payload)
        summary = self._derive_summary(output) or f"python handler {handler_ref}"
        session_messages = [
            {
                "seq": 1,
                "role": "system",
                "type": "instruction",
                "content": (
                    f"Python 节点 {node.code}（{node.name}）由 handler "
                    f"{handler_ref!r} 直接执行，不经过 LLM。"
                ),
            },
            {
                "seq": 2,
                "role": "assistant",
                "type": "final",
                "content": output,
            },
        ]
        next_runtime_state = {
            **snapshot_json(runtime_state or {}),
            "_python_handler": handler_ref,
            "_python_elapsed_seconds": round(elapsed, 3),
            "_summary": summary,
        }
        return SessionTurnResult(
            action=SessionTurnAction.COMPLETE,
            output=output,
            session_memory={},
            session_messages=session_messages,
            runtime_state=next_runtime_state,
            sleep_checkpoint=snapshot_json(sleep_checkpoint or {}),
            compensation_config=snapshot_json(compensation_config or {}),
            summary=summary,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _import_handler(handler_ref: str) -> Any:
        """支持 ``module.path:func`` 与 ``module.path.func`` 两种写法。"""
        if ":" in handler_ref:
            module_name, _, attr = handler_ref.partition(":")
        else:
            module_name, _, attr = handler_ref.rpartition(".")
        if not module_name or not attr:
            raise ValueError(
                f"无法从 {handler_ref!r} 解析 module / function 名。"
            )
        module = importlib.import_module(module_name)
        if not hasattr(module, attr):
            raise AttributeError(
                f"模块 {module_name!r} 中找不到 {attr!r}。"
            )
        handler = getattr(module, attr)
        if not callable(handler):
            raise TypeError(f"{handler_ref!r} 不是可调用对象。")
        return handler

    @staticmethod
    def _derive_summary(output: dict[str, Any]) -> str | None:
        for key in ("summary", "_summary", "message", "msg"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                return text if len(text) <= 200 else text[:197] + "..."
        return None

    @staticmethod
    def _fail(
        node: TaskNodeDefinition,
        *,
        error_message: str,
        runtime_state: dict[str, Any] | None,
        sleep_checkpoint: dict[str, Any] | None,
        compensation_config: dict[str, Any] | None,
        detail: dict[str, Any] | None = None,
    ) -> SessionTurnResult:
        session_messages = [
            {
                "seq": 1,
                "role": "system",
                "type": "instruction",
                "content": (
                    f"Python 节点 {node.code}（{node.name}）执行失败。"
                ),
            },
            {
                "seq": 2,
                "role": "assistant",
                "type": "final",
                "content": {"error": error_message, **(detail or {})},
            },
        ]
        return SessionTurnResult(
            action=SessionTurnAction.FAIL,
            output={"error": error_message, **(detail or {})},
            session_memory={},
            session_messages=session_messages,
            runtime_state={
                **snapshot_json(runtime_state or {}),
                "_summary": error_message[:200],
            },
            sleep_checkpoint=snapshot_json(sleep_checkpoint or {}),
            compensation_config=snapshot_json(compensation_config or {}),
            error_message=error_message,
            summary=error_message[:200],
        )


__all__ = ["PythonNodeRuntime"]
