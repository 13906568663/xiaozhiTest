"""ConversationRuntime 的 usage 记账与只读工具并行执行回归测试。

覆盖两块新能力：

* **usage 记账**：provider 流末尾的 ``{"type": "usage", ...}`` chunk 被 runtime
  消费——累计到 ``turn_usage`` / ``total_usage``、写进最终 Msg 的
  ``metadata["usage"]``、透出 ``usage`` / ``done`` stream 事件，并把最近一次
  真实 prompt token 数记到 ``_last_prompt_tokens``（供压缩触发用）。
* **只读工具并行**：同一批 tool_call 全部满足 ``is_read_only + parallel_safe``
  时并发执行、结果按原顺序合并；任何不满足的工具混入则整批退回串行。

测试不拉真实 LLM：provider 用按脚本产出 chunk 的假实现顶替。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from app.runtime_core.runtime import ConversationRuntime, StreamEvent
from app.runtime_core.tool_protocol import ToolRegistry


class _ScriptedProvider:
    """按脚本逐次返回 chunk 序列的假 provider（只实现 stream_chat）。"""

    def __init__(self, calls: list[list[dict[str, Any]]]) -> None:
        self._calls = list(calls)
        self.n_calls = 0

    async def stream_chat(
        self, messages: list[dict[str, Any]], *, tools: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        script = self._calls[min(self.n_calls, len(self._calls) - 1)]
        self.n_calls += 1
        for chunk in script:
            yield chunk


def _text(t: str) -> dict[str, Any]:
    return {"type": "text_delta", "content": t}


def _tool_call(cid: str, name: str) -> dict[str, Any]:
    return {"type": "tool_call", "id": cid, "name": name, "arguments": "{}"}


def _usage(inp: int, out: int, cache: int = 0) -> dict[str, Any]:
    return {
        "type": "usage",
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cache,
    }


def _run(coro):
    return asyncio.run(coro)


def _make_runtime(
    provider: _ScriptedProvider,
    registry: ToolRegistry | None = None,
    *,
    on_stream=None,
) -> ConversationRuntime:
    return ConversationRuntime(
        provider=provider,  # type: ignore[arg-type]
        registry=registry or ToolRegistry(),
        on_stream=on_stream,
    )


# ---------------------------------------------------------------------------
# usage 记账
# ---------------------------------------------------------------------------


def test_turn_usage_accumulates_across_iterations() -> None:
    """多个 ReAct 迭代的 usage 逐次累计；metadata 与 stream 事件透出。"""

    async def go() -> None:
        registry = ToolRegistry()

        async def echo(**kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

        registry.register_function(
            name="echo", description="echo", parameters=None, fn=echo,
            is_read_only=True, parallel_safe=True,
        )

        provider = _ScriptedProvider([
            [_text("查一下"), _tool_call("c1", "echo"), _usage(100, 20, 10)],
            [_text("完成"), _usage(150, 30)],
        ])
        events: list[StreamEvent] = []

        async def sink(ev: StreamEvent) -> None:
            events.append(ev)

        runtime = _make_runtime(provider, registry, on_stream=sink)
        reply = await runtime.run_turn("hi")

        expected = {
            "input_tokens": 250,
            "output_tokens": 50,
            "cache_read_input_tokens": 10,
            "requests": 2,
        }
        assert runtime.turn_usage.to_dict() == expected
        assert runtime.total_usage.to_dict() == expected
        assert reply.metadata["usage"] == expected
        # 压缩触发依据 = 最近一次调用的真实 prompt tokens
        assert runtime._last_prompt_tokens == 150

        usage_events = [e for e in events if e.type == "usage"]
        assert len(usage_events) == 2
        assert usage_events[0].data["input_tokens"] == 100
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].data["usage"] == expected

    _run(go())


def test_total_usage_spans_turns_while_turn_usage_resets() -> None:
    async def go() -> None:
        provider = _ScriptedProvider([
            [_text("回复一"), _usage(100, 10)],
            [_text("回复二"), _usage(200, 20)],
        ])
        runtime = _make_runtime(provider)

        await runtime.run_turn("第一轮")
        assert runtime.turn_usage.input_tokens == 100

        await runtime.run_turn("第二轮")
        # turn_usage 只含本轮；total_usage 跨轮累计
        assert runtime.turn_usage.input_tokens == 200
        assert runtime.turn_usage.requests == 1
        assert runtime.total_usage.input_tokens == 300
        assert runtime.total_usage.requests == 2

    _run(go())


def test_usage_absent_still_counts_requests() -> None:
    """网关不回报 usage 时：token 全 0，但请求数照常计数、不崩。"""

    async def go() -> None:
        provider = _ScriptedProvider([[_text("无 usage 的回复")]])
        runtime = _make_runtime(provider)
        reply = await runtime.run_turn("hi")

        assert runtime.turn_usage.to_dict() == {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "requests": 1,
        }
        assert runtime._last_prompt_tokens is None
        assert reply.metadata["usage"]["requests"] == 1

    _run(go())


# ---------------------------------------------------------------------------
# 只读工具并行执行
# ---------------------------------------------------------------------------


def _register_slow_tool(
    registry: ToolRegistry,
    name: str,
    log: list[str],
    *,
    parallel_safe: bool,
    is_read_only: bool = True,
    delay: float = 0.05,
) -> None:
    async def fn(**kwargs: Any) -> dict[str, Any]:
        log.append(f"start:{name}")
        await asyncio.sleep(delay)
        log.append(f"end:{name}")
        return {"tool": name}

    fn.__name__ = name
    registry.register_function(
        name=name, description=name, parameters=None, fn=fn,
        is_read_only=is_read_only, parallel_safe=parallel_safe,
    )


def test_parallel_safe_batch_executes_concurrently_and_keeps_order() -> None:
    async def go() -> None:
        registry = ToolRegistry()
        log: list[str] = []
        _register_slow_tool(registry, "slow_a", log, parallel_safe=True)
        _register_slow_tool(registry, "slow_b", log, parallel_safe=True)

        provider = _ScriptedProvider([
            [_tool_call("c1", "slow_a"), _tool_call("c2", "slow_b")],
            [_text("done")],
        ])
        runtime = _make_runtime(provider, registry)
        await runtime.run_turn("go")

        # 并发：两个 start 都先于任何 end 出现
        assert log[0].startswith("start:") and log[1].startswith("start:")
        assert {log[0], log[1]} == {"start:slow_a", "start:slow_b"}

        # 结果按原 tool_call 顺序合并（配对协议 + 前端时间线依赖顺序稳定）
        tool_result_msgs = [
            m for m in runtime.memory.get_memory()
            if m.get_content_blocks("tool_result")
        ]
        assert len(tool_result_msgs) == 1
        blocks = tool_result_msgs[0].get_content_blocks("tool_result")
        assert [b["id"] for b in blocks] == ["c1", "c2"]

    _run(go())


def test_mixed_batch_falls_back_to_sequential() -> None:
    async def go() -> None:
        registry = ToolRegistry()
        log: list[str] = []
        _register_slow_tool(registry, "slow_a", log, parallel_safe=True)
        # writer 未声明 parallel_safe（且非只读）→ 整批退回串行
        _register_slow_tool(
            registry, "writer", log, parallel_safe=False, is_read_only=False,
        )

        provider = _ScriptedProvider([
            [_tool_call("c1", "slow_a"), _tool_call("c2", "writer")],
            [_text("done")],
        ])
        runtime = _make_runtime(provider, registry)
        await runtime.run_turn("go")

        assert log == ["start:slow_a", "end:slow_a", "start:writer", "end:writer"]

    _run(go())


def test_readonly_without_parallel_safe_stays_sequential() -> None:
    """只读但未显式声明 parallel_safe 的工具（如共享 db_session 的检索工具）不并发。"""

    async def go() -> None:
        registry = ToolRegistry()
        log: list[str] = []
        _register_slow_tool(registry, "ro_a", log, parallel_safe=False)
        _register_slow_tool(registry, "ro_b", log, parallel_safe=False)

        provider = _ScriptedProvider([
            [_tool_call("c1", "ro_a"), _tool_call("c2", "ro_b")],
            [_text("done")],
        ])
        runtime = _make_runtime(provider, registry)
        await runtime.run_turn("go")

        assert log == ["start:ro_a", "end:ro_a", "start:ro_b", "end:ro_b"]

    _run(go())
