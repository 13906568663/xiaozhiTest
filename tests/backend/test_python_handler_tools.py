"""``register_python_handler_tools`` 单测：

验证「把进程内 Python handler 暴露成 AGENT 节点可调工具」这一通路：
* 工具名 / 描述 / 参数 schema 取自 ``python_handler_config`` 的保留键
* 调用工具 = 调用 handler，上下文 / handler_config 正确透传
* 保留键（tool_name 等）不会污染 handler_config
* handler 缺失 / 加载失败 / 返回非 dict 的兜底行为
"""

from __future__ import annotations

import pytest

from app.runtime_core.tool_protocol import ToolContext, ToolRegistry
from app.workflow.runtime.tool_registry import register_python_handler_tools
from app.workflow.schemas import TaskNodeDefinition


# 供工具按 import 路径加载的测试 handler（签名与 PythonNodeRuntime 协议一致）。
# 注意：不要用模块级变量做断言——pytest 与 importlib 可能加载到不同的模块实例，
# 副作用对不上；统一把要校验的东西放进返回值里。
async def _echo_handler(context, *, db_session, runtime_context, handler_config, node):
    return {
        "ok": True,
        "seen_flag": handler_config.get("flag"),
        "from_ctx": context.get("x"),
        "arg_echo": handler_config.get("override"),
        "cfg_keys": sorted(handler_config.keys()),
    }


async def _bad_handler(context, *, db_session, runtime_context, handler_config, node):
    return ["not", "a", "dict"]


async def _raising_handler(context, *, db_session, runtime_context, handler_config, node):
    raise RuntimeError("boom")


def _node(handler_ref: str | None, cfg: dict) -> TaskNodeDefinition:
    return TaskNodeDefinition(
        seq=1,
        code="step_x",
        name="测试节点",
        executor="agent",
        python_handler=handler_ref,
        python_handler_config=cfg,
    )


_MOD = "tests.backend.test_python_handler_tools"


@pytest.mark.asyncio
async def test_registers_tool_and_runs_handler():
    reg = ToolRegistry()
    node = _node(
        f"{_MOD}:_echo_handler",
        {"flag": "v1", "tool_name": "my_tool", "tool_description": "做某事"},
    )
    register_python_handler_tools(
        reg, node, {"x": 42}, db_session=None, runtime_context={"node_run_id": "n1"},
    )

    assert reg.has("my_tool")
    defs = {d["function"]["name"]: d["function"] for d in reg.openai_definitions()}
    assert "my_tool" in defs
    assert defs["my_tool"]["description"] == "做某事"

    res = await reg.execute("my_tool", {}, ToolContext())
    assert res.is_error is False
    assert res.output["ok"] is True
    assert res.output["seen_flag"] == "v1"
    assert res.output["from_ctx"] == 42
    # 保留键不应进入 handler_config
    assert "tool_name" not in res.output["cfg_keys"]
    assert "tool_description" not in res.output["cfg_keys"]
    assert "flag" in res.output["cfg_keys"]


@pytest.mark.asyncio
async def test_tool_name_defaults_to_node_code():
    reg = ToolRegistry()
    node = _node(f"{_MOD}:_echo_handler", {})
    register_python_handler_tools(reg, node, {}, db_session=None, runtime_context={})
    assert reg.has("run_step_x")


@pytest.mark.asyncio
async def test_llm_args_merge_into_handler_config():
    reg = ToolRegistry()
    node = _node(f"{_MOD}:_echo_handler", {"tool_name": "t"})
    register_python_handler_tools(reg, node, {}, db_session=None, runtime_context={})
    res = await reg.execute("t", {"override": "from_llm"}, ToolContext())
    assert res.output["arg_echo"] == "from_llm"


@pytest.mark.asyncio
async def test_no_handler_registers_nothing():
    reg = ToolRegistry()
    node = _node(None, {})
    register_python_handler_tools(reg, node, {}, db_session=None, runtime_context={})
    assert reg.openai_definitions() == []


@pytest.mark.asyncio
async def test_import_failure_is_swallowed():
    reg = ToolRegistry()
    node = _node(f"{_MOD}:_does_not_exist", {"tool_name": "t"})
    register_python_handler_tools(reg, node, {}, db_session=None, runtime_context={})
    # 加载失败只跳过该工具，不抛异常、不注册
    assert not reg.has("t")


@pytest.mark.asyncio
async def test_non_dict_return_is_error():
    reg = ToolRegistry()
    node = _node(f"{_MOD}:_bad_handler", {"tool_name": "t"})
    register_python_handler_tools(reg, node, {}, db_session=None, runtime_context={})
    res = await reg.execute("t", {}, ToolContext())
    assert res.is_error is True
    assert "dict" in res.output["error"]


@pytest.mark.asyncio
async def test_handler_exception_becomes_error_result():
    reg = ToolRegistry()
    node = _node(f"{_MOD}:_raising_handler", {"tool_name": "t"})
    register_python_handler_tools(reg, node, {}, db_session=None, runtime_context={})
    res = await reg.execute("t", {}, ToolContext())
    assert res.is_error is True
    assert "boom" in res.output["error"]
