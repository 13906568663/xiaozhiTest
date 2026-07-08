"""Python 节点运行时单测。

确保：
* handler 返回 dict 时被包装成 ``SessionTurnAction.COMPLETE``；
* handler 抛异常 / 超时 / 不存在时落 FAIL，且 error_message 可读；
* handler_config / runtime_context 正确透传。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.domain.enums import NodeExecutorType
from app.workflow.runtime.python_node_runtime import PythonNodeRuntime
from app.workflow.runtime.types import SessionTurnAction
from app.workflow.schemas import TaskNodeDefinition


# 模块级 handler（供 importlib 解析）—— 通过字符串 import 路径调用，故而
# 静态检查会误判「未使用」，实际是这套测试的核心被测对象。
async def _ok_handler(  # noqa: F841  # imported by string path
    context: dict[str, Any],
    *,
    db_session: Any,
    runtime_context: dict[str, Any],
    handler_config: dict[str, Any],
    node: Any,
) -> dict[str, Any]:
    return {
        "echo_ctx_keys": sorted(context.keys()),
        "got_handler_config": handler_config,
        "got_runtime_ctx_task_run": runtime_context.get("task_run_id"),
        "summary": "ok",
    }


async def _boom_handler(  # noqa: F841  # imported by string path
    context: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    raise RuntimeError("intentional boom")


async def _slow_handler(  # noqa: F841  # imported by string path
    context: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    await asyncio.sleep(5)
    return {}


def _make_node(*, handler: str, config: dict[str, Any] | None = None) -> TaskNodeDefinition:
    return TaskNodeDefinition(
        seq=1,
        code="test_py",
        name="test",
        executor=NodeExecutorType.PYTHON,
        python_handler=handler,
        python_handler_config=config or {},
    )


def test_python_runtime_complete_path() -> None:
    async def go() -> None:
        node = _make_node(
            handler="tests.backend.test_python_node_runtime:_ok_handler",
            config={"foo": "bar"},
        )
        result = await PythonNodeRuntime().run_python_handler(
            node,
            {"upstream": {"x": 1}},
            runtime_context={"task_run_id": "T-1"},
        )
        assert result.action == SessionTurnAction.COMPLETE
        assert result.output["got_handler_config"] == {"foo": "bar"}
        assert result.output["got_runtime_ctx_task_run"] == "T-1"
        # 至少 2 条 session_messages（instruction + final）
        assert len(result.session_messages) >= 2
        assert result.summary == "ok"

    asyncio.run(go())


def test_python_runtime_failed_when_handler_raises() -> None:
    async def go() -> None:
        node = _make_node(
            handler="tests.backend.test_python_node_runtime:_boom_handler",
        )
        result = await PythonNodeRuntime().run_python_handler(node, {})
        assert result.action == SessionTurnAction.FAIL
        assert "intentional boom" in (result.error_message or "")

    asyncio.run(go())


def test_python_runtime_failed_when_handler_missing() -> None:
    async def go() -> None:
        node = _make_node(
            handler="tests.backend.test_python_node_runtime:_does_not_exist",
        )
        result = await PythonNodeRuntime().run_python_handler(node, {})
        assert result.action == SessionTurnAction.FAIL
        assert "找不到" in (result.error_message or "")

    asyncio.run(go())


def test_python_runtime_failed_when_no_handler_configured() -> None:
    async def go() -> None:
        node = _make_node(handler="")
        result = await PythonNodeRuntime().run_python_handler(node, {})
        assert result.action == SessionTurnAction.FAIL
        assert "python_handler" in (result.error_message or "")

    asyncio.run(go())


def test_python_runtime_timeout() -> None:
    async def go() -> None:
        node = _make_node(
            handler="tests.backend.test_python_node_runtime:_slow_handler",
            config={"timeout_seconds": 0.2},
        )
        result = await PythonNodeRuntime().run_python_handler(node, {})
        assert result.action == SessionTurnAction.FAIL
        assert "超时" in (result.error_message or "")

    asyncio.run(go())
