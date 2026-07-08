"""ConversationRuntime — the agent loop.

设计目标
~~~~~~~~
* 单回合 ``run_turn(input_messages) -> Msg``：跑完一轮 ReAct，直到模型不再
  发起 tool_call 或调用了 ``finish_tool_name`` 终止工具。
* 用 OpenAI 函数调用协议（``tools=[...]`` / ``tool_calls=[...]``）作为唯一
  推理协议。
* 与 ``NodeSessionDecision`` 的耦合通过"内置 finish 工具"完成：runtime 在
  注册时插入一个 ``generate_response`` 工具，schema 由调用方通过
  ``finish_tool_schema`` 提供。模型调用该工具即代表本回合结束，工具入参原
  样塞进 reply.metadata 并退出循环。
* Hooks：在 reply / reasoning / acting 三个阶段提供 pre/post 钩子。

注意：不实现 fool-code 的"权限弹窗 / 动态 skill / MAGMA / Plan Mode" 等桌面
能力——这些超出 agent-flow 范围。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.runtime_core.compression import (
    CompressionConfig,
    maybe_compress,
)
from app.runtime_core.formatter import ChatFormatter
from app.runtime_core.hooks import HookRunner, HookStage
from app.runtime_core.memory import Memory
from app.runtime_core.messages import (
    Msg,
    MsgRole,
    image_block,
    text_block,
    thinking_block,
    tool_result_block,
    tool_use_block,
)
from app.runtime_core.provider import OpenAICompatProvider, TokenUsage
from app.runtime_core.tool_protocol import (
    ToolCategory,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
)

logger = logging.getLogger(__name__)


DEFAULT_FINISH_TOOL_NAME = "generate_response"


@dataclass
class FinishConfig:
    """Tells the runtime how to recognise / parse the "finish" tool call."""

    name: str = DEFAULT_FINISH_TOOL_NAME
    description: str = (
        "Call this special tool exactly once, as the final action of this turn, "
        "to deliver your structured decision back to the workflow engine."
    )
    parameters: dict[str, Any] = field(default_factory=lambda: {
        "type": "object", "properties": {}, "required": [],
    })
    # Optional callback to validate/normalise the captured payload (raises on error).
    validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass
class StreamEvent:
    """Stream events emitted by ``run_turn_streaming``."""

    # "text_delta" | "thinking_delta" | "tool_call" | "tool_result" | "usage" | "done"
    type: str
    data: dict[str, Any]


StreamSink = Callable[[StreamEvent], Awaitable[None] | None]


class ConversationRuntime:
    """Run multi-turn ReAct with the configured provider / tool registry / hooks."""

    def __init__(
        self,
        *,
        provider: OpenAICompatProvider,
        registry: ToolRegistry,
        memory: Memory | None = None,
        formatter: ChatFormatter | None = None,
        hooks: HookRunner | None = None,
        compression: CompressionConfig | None = None,
        sys_prompt: str | None = None,
        finish: FinishConfig | None = None,
        max_iters: int = 20,
        name: str = "agent",
        on_stream: StreamSink | None = None,
        tool_output_postprocessor: Any | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        # 注意：必须用 `is not None` 而不是 `or`。Memory 实现了 __len__，
        # 空 Memory 的 bool() 是 False，``memory or Memory()`` 会把外部
        # 传入的空 memory 丢掉、用内部新建的，导致：
        #   - ReAct loop 的所有 tool_call/tool_result 写进内部 memory
        #   - 调用方拿外部 memory 做 state_dict()/持久化时只看到空内容
        #   - NodeRun.session_memory_json 永远空 → 多轮恢复丢上下文
        #   - NodeRun.session_messages_json 只剩 system + final，2 条消息
        # 该 bug 直接表现为：子专家 transcript 显示残缺、跨 turn 失忆。
        self.memory = memory if memory is not None else Memory()
        self.formatter = formatter if formatter is not None else ChatFormatter()
        self.hooks = hooks if hooks is not None else HookRunner()
        self.compression = compression or CompressionConfig(enable=False)
        self.sys_prompt = sys_prompt
        self.finish = finish
        self.max_iters = max(1, int(max_iters))
        self.name = name
        self.on_stream = on_stream
        # 可选钩子：在 tool_result 灌进 LLM memory 之前对 output 文本做一次后处理。
        # 主要用途：把超大工具返回（如 50KB+ 的查询结果）立即转存为 artifact，
        # 给 LLM 看到一个含 artifact_id 的 stub JSON，让 LLM 能在后续 generate_response
        # 中用 ref 引用（避免把大数据再 token-by-token 输出，绕开 max_tokens 截断）。
        #   signature: async (tool_name: str, output_text: str) -> str
        # 抛异常时打 warning + 回退到原始 output（不阻断工具链）。
        self.tool_output_postprocessor = tool_output_postprocessor

        # Per-turn state（每次 run_turn 重置）。
        self._captured_decision: dict[str, Any] | None = None
        # 本轮所有 assistant 文本段（按 ReAct 迭代顺序）。
        # 模型经常把"长篇交付物正文"（表格/明细/SQL）和 tool_call 放在同一条
        # assistant 消息里，最后一轮只剩一句"以上即为…"的收尾——若调用方只取
        # run_turn 返回的最后一条消息的文本，正文会整段丢失（用户流式看到表格
        # 闪过、落库后消失）。调用方应优先用本列表拼接完整回复。
        self.last_turn_texts: list[str] = []
        # Token 用量记账：turn_usage 每次 run_turn 重置；total_usage 覆盖 runtime
        # 生命周期内的全部 LLM 调用。数据来自 provider 的 usage chunk
        # （stream_options.include_usage），部分网关不回报时只有 requests 计数。
        self.turn_usage = TokenUsage()
        self.total_usage = TokenUsage()
        # 最近一次 LLM 调用的真实 prompt token 数（provider 回报的
        # usage.input_tokens）。作为压缩触发的权威依据传给 maybe_compress——
        # 字符估算对工具 schema / 多模态内容一无所知，真实值能兜住低估。
        self._last_prompt_tokens: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_turn(
        self,
        input_messages: list[Msg] | Msg | str,
        *,
        context: ToolContext | None = None,
        timeout: float | None = None,
    ) -> Msg:
        """Run one full ReAct turn. Returns the final assistant ``Msg``."""
        ctx = context or ToolContext()
        if isinstance(input_messages, Msg):
            input_messages = [input_messages]
        elif isinstance(input_messages, str):
            input_messages = [Msg.user(input_messages)]

        coro = self._run_turn_inner(input_messages, ctx)
        if timeout and timeout > 0:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    # ------------------------------------------------------------------
    # Inner loop
    # ------------------------------------------------------------------

    async def _run_turn_inner(
        self, input_messages: list[Msg], ctx: ToolContext,
    ) -> Msg:
        self._captured_decision = None
        self.last_turn_texts = []
        self.turn_usage = TokenUsage()
        for m in input_messages:
            self.memory.add_message(m)

        pre_reply_payload = await self.hooks.run(
            HookStage.PRE_REPLY,
            {"runtime": self, "context": ctx},
        )
        # PRE_REPLY hook 可以通过返回 ``_blocked=True`` 让 runtime 跳过整轮
        # LLM 推理，直接用 ``message`` 作为助手回复（例如敏感词 reject 模式）。
        if pre_reply_payload.get("_blocked"):
            blocked_text = pre_reply_payload.get("message") or "[blocked]"
            blocked_reply = Msg.assistant([text_block(blocked_text)])
            self.memory.add_message(blocked_reply)
            self.last_turn_texts.append(blocked_text)
            if self.on_stream:
                await _maybe_await(self.on_stream(
                    StreamEvent("text_delta", {"content": blocked_text})
                ))
            await self.hooks.run(
                HookStage.POST_REPLY,
                {"msg": blocked_reply, "context": ctx},
            )
            if self.on_stream:
                await _maybe_await(self.on_stream(
                    StreamEvent("done", {"usage": self.turn_usage.to_dict()})
                ))
            return blocked_reply

        last_assistant: Msg | None = None
        max_llm_retries = 2
        # exhausted: 当 for-loop 自然走到 self.max_iters 且没有任何 break 出去
        # （即既没有「assistant 不再调工具」也没有 finish-tool）时为 True。
        # 这种情况下底层会直接结束本 turn 而不写任何提示，前端聊天面板会
        # 看到「卡了几分钟然后什么都没有」的现象——典型场景：主 AI 陷入
        # restart→run_subagent→cancel→redo→cancel 循环把工具配额吃光。
        # 在结尾给用户兜一条提示，避免无消息可看。
        exhausted = True
        try:
            for iteration in range(self.max_iters):
                # 1) (optional) compression before each reasoning step
                if self.compression.enable:
                    try:
                        compressed = await maybe_compress(
                            memory=self.memory,
                            formatter=self.formatter,
                            provider=self.provider,
                            config=self.compression,
                            observed_tokens=self._last_prompt_tokens,
                        )
                        if compressed:
                            # 压缩后 memory 已瘦身，上一次调用的真实 prompt token
                            # 数不再代表当前上下文；重置为 None 回退到估算，
                            # 直到下一次 LLM 调用回报新的 usage。否则会拿着
                            # 压缩前的大数字反复触发压缩。
                            self._last_prompt_tokens = None
                    except Exception:
                        logger.exception("[%s] compression failed; continuing", self.name)

                # 2) pre_reasoning hook (can mutate sys_prompt etc. via ctx.extra)
                await self.hooks.run(
                    HookStage.PRE_REASONING,
                    {"iteration": iteration, "context": ctx},
                )

                # Reasoning with retry: 如果上一条是 tool_results，但本次 LLM
                # 调用没有任何 text 也没有 tool_call，说明模型瞬时调用失败。
                # 这种情况下直接退出会让用户重发一次消息——而那些已经执行
                # 的工具结果就白费了。借鉴 fool-code，做有限次重试。
                _all_msgs = self.memory.get_memory()
                last_msg = _all_msgs[-1] if _all_msgs else None
                has_pending_tool_results = bool(
                    last_msg
                    and hasattr(last_msg, "get_content_blocks")
                    and last_msg.get_content_blocks("tool_result")
                )
                llm_retry = 0
                while True:
                    assistant_msg = await self._reasoning_step()
                    is_empty = (
                        not assistant_msg.get_content_blocks("tool_use")
                        and not (assistant_msg.get_text_content() or "").strip()
                    )
                    if (
                        is_empty
                        and has_pending_tool_results
                        and llm_retry < max_llm_retries
                    ):
                        llm_retry += 1
                        logger.warning(
                            "[%s] LLM returned empty after tool result at iter=%d "
                            "(retry %d/%d)",
                            self.name, iteration, llm_retry, max_llm_retries,
                        )
                        await asyncio.sleep(1.0 * llm_retry)
                        continue
                    break

                self.memory.add_message(assistant_msg)
                last_assistant = assistant_msg
                step_text = assistant_msg.get_text_content() or ""
                if step_text.strip():
                    self.last_turn_texts.append(step_text)

                await self.hooks.run(
                    HookStage.POST_REASONING,
                    {"iteration": iteration, "msg": assistant_msg, "context": ctx},
                )

                tool_uses = assistant_msg.get_content_blocks("tool_use")
                if not tool_uses:
                    exhausted = False
                    break

                # _acting_step 内部已保证每个 tool_use 都有配对 tool_result
                # （含 catch-all 兜底）。这里若再抛异常就交给外层 try 处理。
                results = await self._acting_step(tool_uses, ctx)
                if results:
                    self.memory.add_message(Msg.tool_results(results))

                # If a finish tool was called, exit the loop now.
                if self._captured_decision is not None:
                    exhausted = False
                    break
        finally:
            # Repair invariant: 不论循环正常结束还是异常中断，都要保证 memory
            # 里所有 tool_use 都有配对 tool_result。否则 session_memory_json
            # dump 出去后下一轮 resume 直接 OpenAI 422。
            self._repair_dangling_tool_uses()

        if exhausted:
            logger.warning(
                "[%s] reached max_iters=%d without a natural finish; "
                "appending fallback notice so user-facing chat is not silent",
                self.name, self.max_iters,
            )
            notice_text = (
                f"[已达最大执行步数 {self.max_iters}，本回合中止；"
                f"如需继续请再次发送消息。]"
            )
            notice = text_block(f"\n\n{notice_text}")
            self.last_turn_texts.append(notice_text)
            if last_assistant is None or not last_assistant.blocks:
                last_assistant = Msg.assistant([
                    text_block(
                        f"[已达最大执行步数 {self.max_iters}，本回合中止；"
                        f"如需继续请再次发送消息。]"
                    )
                ])
            else:
                # 已经有内容（可能只是 tool_use 没文本），追加一条文本块
                # 让上层 chat_engine 把它写进 ChatMessage.content，避免
                # ChatMessage 入库时 content 为空被静默丢弃。
                last_assistant.blocks.append(notice)

        if last_assistant is None:
            last_assistant = Msg.assistant([text_block("(no response)")])

        # Stash captured decision into metadata so callers can read it.
        if self._captured_decision is not None:
            last_assistant.metadata["decision"] = self._captured_decision
        last_assistant.metadata["usage"] = self.turn_usage.to_dict()

        await self.hooks.run(
            HookStage.POST_REPLY,
            {"msg": last_assistant, "context": ctx},
        )

        if self.on_stream:
            await _maybe_await(self.on_stream(
                StreamEvent("done", {"usage": self.turn_usage.to_dict()})
            ))

        return last_assistant

    def _repair_dangling_tool_uses(self) -> None:
        """Append fallback tool_results for any tool_use blocks that didn't
        get one (e.g. acting step was interrupted mid-loop).
        """
        pending = _collect_pending_tool_use_ids(self.memory)
        if not pending:
            return
        logger.warning(
            "[%s] repairing %d dangling tool_use(s) with fallback tool_results",
            self.name, len(pending),
        )
        fallback_blocks = [
            tool_result_block(
                cid, name,
                "工具调用未完成（执行被中断或运行时异常），请换一种方式重试，"
                "或直接告知用户当前遇到的问题。",
                is_error=True,
            )
            for cid, name in pending
        ]
        self.memory.add_message(Msg.tool_results(fallback_blocks))

    # ------------------------------------------------------------------
    # Reasoning (one LLM call, collects text + tool_calls)
    # ------------------------------------------------------------------

    async def _reasoning_step(self) -> Msg:
        msgs = self.memory.get_memory()
        formatted = self.formatter.format(
            msgs,
            sys_prompt=self.sys_prompt,
            compressed_summary=self.memory.compressed_summary,
        )
        tools = self._build_tool_definitions()

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        first_token_at: float | None = None
        start = time.perf_counter()
        logger.info(
            "[%s] reasoning start: %d msgs, %d tools",
            self.name, len(formatted), len(tools),
        )
        self.turn_usage.requests += 1
        self.total_usage.requests += 1
        call_usage: dict[str, int] | None = None

        async for chunk in self.provider.stream_chat(formatted, tools=tools):
            t = chunk.get("type")
            if t == "text_delta":
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                text_parts.append(chunk["content"])
                if self.on_stream:
                    await _maybe_await(self.on_stream(
                        StreamEvent("text_delta", {"content": chunk["content"]})
                    ))
            elif t == "thinking_delta":
                thinking_parts.append(chunk["content"])
                if self.on_stream:
                    await _maybe_await(self.on_stream(
                        StreamEvent("thinking_delta", {"content": chunk["content"]})
                    ))
            elif t == "tool_call":
                tool_calls.append({
                    "id": chunk["id"],
                    "name": chunk["name"],
                    "arguments": chunk.get("arguments") or "{}",
                })
            elif t == "usage":
                call_usage = {
                    "input_tokens": int(chunk.get("input_tokens") or 0),
                    "output_tokens": int(chunk.get("output_tokens") or 0),
                    "cache_read_input_tokens": int(
                        chunk.get("cache_read_input_tokens") or 0
                    ),
                }
            elif t == "error":
                msg = chunk.get("message", "unknown LLM error")
                logger.warning("[%s] LLM stream error: %s", self.name, msg)
                # Surface the error as a text block so caller can see it.
                text_parts.append(f"\n\n[模型调用失败] {msg}")

        if call_usage is not None:
            self.turn_usage.record(**call_usage)
            self.total_usage.record(**call_usage)
            if call_usage["input_tokens"] > 0:
                self._last_prompt_tokens = call_usage["input_tokens"]
            if self.on_stream:
                await _maybe_await(self.on_stream(
                    StreamEvent("usage", dict(call_usage))
                ))

        elapsed = time.perf_counter() - start
        ttft = (first_token_at - start) if first_token_at else None
        logger.info(
            "[%s] reasoning done in %.2fs (ttft=%.2fs, text=%d chars, tool_calls=%d, "
            "prompt_tokens=%s, completion_tokens=%s)",
            self.name,
            elapsed,
            ttft if ttft is not None else 0.0,
            sum(len(p) for p in text_parts),
            len(tool_calls),
            call_usage["input_tokens"] if call_usage else "n/a",
            call_usage["output_tokens"] if call_usage else "n/a",
        )

        blocks: list[dict[str, Any]] = []
        if thinking_parts:
            blocks.append(thinking_block("".join(thinking_parts)))
        if text_parts:
            blocks.append(text_block("".join(text_parts)))
        for tc in tool_calls:
            try:
                args_dict = json.loads(tc["arguments"]) if tc["arguments"] else {}
                if not isinstance(args_dict, dict):
                    args_dict = {"_value": args_dict}
            except json.JSONDecodeError:
                args_dict = {"_raw": tc["arguments"]}
            blocks.append(tool_use_block(tc["id"], tc["name"], args_dict))
            if self.on_stream:
                await _maybe_await(self.on_stream(StreamEvent(
                    "tool_call",
                    {
                        "id": tc["id"],
                        "name": tc["name"],
                        "arguments": args_dict,
                    },
                )))

        if not blocks:
            blocks.append(text_block(""))
        return Msg.assistant(blocks, name=self.name)

    # ------------------------------------------------------------------
    # Acting (run each tool_call in order, return result blocks)
    # ------------------------------------------------------------------

    async def _acting_step(
        self,
        tool_uses: list[dict[str, Any]],
        ctx: ToolContext,
    ) -> list[dict[str, Any]]:
        """Execute every ``tool_use`` and return matching ``tool_result`` blocks.

        Critical invariant: 每个传入的 ``tool_use`` 必须在返回的 results 里有
        对应的 ``tool_result``——否则下一次 LLM 调用会因为 OpenAI tool_call/
        tool_result 配对协议被破坏而 422。哪怕外层 hook、metadata 处理、
        image promote 等任意环节抛了未预期异常，都要兜底成一条 error
        tool_result，绝不能让 ``tool_use`` 悬空。

        并行策略：当一次 assistant 响应携带多个 tool_call 且**全部**同时满足
        ``is_read_only=True`` 与 ``parallel_safe=True``（注册方显式声明无共享
        状态；MCP / finish / 未知工具一律不算）时，并发执行以省掉串行等待；
        结果按原 tool_call 顺序合并，保证配对与展示顺序稳定。任何不满足条件的
        工具混入批次即整批退回串行。
        """
        if len(tool_uses) > 1 and self._all_parallelizable(tool_uses):
            buckets: list[list[dict[str, Any]]] = [[] for _ in tool_uses]
            await asyncio.gather(*(
                self._run_tool_safely(tu, ctx, bucket)
                for tu, bucket in zip(tool_uses, buckets)
            ))
            merged: list[dict[str, Any]] = []
            for bucket in buckets:
                merged.extend(bucket)
            return merged

        results: list[dict[str, Any]] = []
        for tu in tool_uses:
            await self._run_tool_safely(tu, ctx, results)
        return results

    def _all_parallelizable(self, tool_uses: list[dict[str, Any]]) -> bool:
        """整批 tool_call 是否可以安全并发：全部只读且显式声明 parallel_safe。"""
        for tu in tool_uses:
            name = str(tu.get("name") or "")
            if self.finish and name == self.finish.name:
                return False
            if not self.registry.is_read_only(name):
                return False
            if not self.registry.is_parallel_safe(name):
                return False
        return True

    async def _run_tool_safely(
        self,
        tu: dict[str, Any],
        ctx: ToolContext,
        results: list[dict[str, Any]],
    ) -> None:
        """执行单个 tool_use，任何未预期异常都兜底成 error tool_result。"""
        call_id = str(tu.get("id") or "")
        name = str(tu.get("name") or "")
        try:
            await self._handle_one_tool(tu, call_id, name, ctx, results)
        except Exception as exc:
            logger.exception(
                "[%s] FATAL: unhandled error processing tool %s",
                self.name, name,
            )
            if not _has_result_for(results, call_id):
                results.append(tool_result_block(
                    call_id, name,
                    f"工具执行时发生内部错误 ({type(exc).__name__}): {exc}。"
                    "请换一种方式完成任务，或告知用户当前遇到的问题。",
                    is_error=True,
                ))
            if self.on_stream:
                try:
                    await _maybe_await(self.on_stream(StreamEvent(
                        "tool_result",
                        {
                            "id": call_id,
                            "tool_name": name,
                            "is_error": True,
                            "output": f"内部错误: {type(exc).__name__}: {exc}",
                        },
                    )))
                except Exception:
                    pass

    async def _handle_one_tool(
        self,
        tu: dict[str, Any],
        call_id: str,
        name: str,
        ctx: ToolContext,
        results: list[dict[str, Any]],
    ) -> None:
        args = tu.get("input") or {}
        if not isinstance(args, dict):
            args = {"_value": args}

        # finish tool is intercepted before normal dispatch
        if self.finish and name == self.finish.name:
            payload = self._capture_finish(args)
            output = payload or {"ok": True}
            # validator 失败时 _capture_finish 不会设 _captured_decision，
            # 此时返回的 output 形如 {"ok": False, "error": ..., "hint": ...}
            # —— 写回 memory 时标 is_error=True，让 LLM 明确知道这是失败
            # 的 finish 调用，需要在下一轮修正后重新调。
            finish_failed = (
                isinstance(output, dict) and output.get("ok") is False
            )
            results.append(tool_result_block(
                call_id, name, output, is_error=finish_failed,
            ))
            # 必须为 finish tool 也发一次 tool_result stream 事件，否则前端
            # ActionTimeline 收到了 tool_call 却永远等不到对应的 tool_result，
            # 该工具会一直显示"执行中"（即使整轮对话已结束）。
            if self.on_stream:
                try:
                    preview = (
                        json.dumps(output, ensure_ascii=False)
                        if not isinstance(output, str)
                        else output
                    )
                except Exception:
                    preview = str(output)
                if len(preview) > 4000:
                    preview = preview[:4000] + "...[truncated]"
                await _maybe_await(self.on_stream(StreamEvent(
                    "tool_result",
                    {
                        "id": call_id,
                        "tool_name": name,
                        "is_error": finish_failed,
                        "output": preview,
                    },
                )))
            return

        pre = await self.hooks.run(
            HookStage.PRE_ACTING,
            {"tool_name": name, "arguments": args, "context": ctx},
        )
        if pre.get("_blocked"):
            blocked_msg = pre.get("message") or "blocked by hook"
            results.append(tool_result_block(
                call_id, name, {"error": blocked_msg}, is_error=True,
            ))
            return
        args = pre.get("arguments", args)

        # 测量工具执行耗时，并从 registry 拉出 category 一并传到 POST_ACTING
        # hook payload，便于上层（如 tool_call_logger）按类别分流统计。
        # 取不到 handler（典型如 MCP 工具走的是 _mcp_invokers）时降级标记为
        # ``ToolCategory.MCP``，未知工具兜底 ``META``。
        _execute_start = time.perf_counter()
        try:
            tool_result = await self.registry.execute(name, args, ctx)
        except Exception as exc:
            logger.exception("[%s] tool %s execution crashed", self.name, name)
            tool_result = ToolResult(
                output={"error": str(exc)}, is_error=True,
            )
        duration_ms = int((time.perf_counter() - _execute_start) * 1000)

        handler = self.registry.get_handler(name)
        if handler is not None:
            category = handler.meta.category
        elif self.registry.is_mcp_tool(name):
            category = ToolCategory.MCP
        else:
            category = ToolCategory.META

        try:
            await self.hooks.run(
                HookStage.POST_ACTING,
                {
                    "tool_name": name,
                    "arguments": args,
                    "result": tool_result,
                    "context": ctx,
                    "category": category,
                    "duration_ms": duration_ms,
                },
            )
        except Exception:
            logger.exception("[%s] post_acting hook crashed for %s", self.name, name)

        output = tool_result.output_text() if isinstance(tool_result, ToolResult) else str(tool_result)
        # 给上层注入"大对象转 artifact + stub 替换"的机会；失败时静默回退，确保
        # 不让一个可选优化路径阻断工具链。
        if self.tool_output_postprocessor is not None:
            try:
                postprocessed = await _maybe_await(
                    self.tool_output_postprocessor(name, output)
                )
                if isinstance(postprocessed, str):
                    output = postprocessed
            except Exception:
                logger.exception(
                    "[%s] tool_output_postprocessor crashed for %s; using raw output",
                    self.name,
                    name,
                )
        results.append(tool_result_block(
            call_id, name, output, is_error=bool(getattr(tool_result, "is_error", False)),
        ))

        # Promote images stashed in metadata (e.g. tool-captured screenshots)
        # to image blocks on the same tool_results Msg so the formatter can lift
        # them into a follow-up user message via promote_tool_result_images=True.
        if isinstance(tool_result, ToolResult):
            for img in tool_result.metadata.get("images", []) or []:
                if not isinstance(img, dict):
                    continue
                try:
                    results.append(image_block(
                        url=img.get("url"),
                        data=img.get("data"),
                        media_type=img.get("media_type") or "image/jpeg",
                    ))
                except Exception:
                    logger.exception("[%s] failed to promote image block", self.name)

        if self.on_stream:
            preview = output if isinstance(output, str) else str(output)
            if len(preview) > 4000:
                preview = preview[:4000] + "...[truncated]"
            await _maybe_await(self.on_stream(StreamEvent(
                "tool_result",
                {
                    "id": call_id,
                    "tool_name": name,
                    "is_error": bool(getattr(tool_result, "is_error", False)),
                    "output": preview,
                },
            )))

    # ------------------------------------------------------------------
    # Tool definitions (built-in finish tool gets injected here)
    # ------------------------------------------------------------------

    def _build_tool_definitions(self) -> list[dict[str, Any]]:
        defs = list(self.registry.openai_definitions())
        if self.finish:
            defs.append(ToolDefinition(
                name=self.finish.name,
                description=self.finish.description,
                parameters=self.finish.parameters,
            ).to_openai_dict())
        return defs

    def _capture_finish(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.finish:
            return payload
        if self.finish.validator:
            try:
                validated = self.finish.validator(payload)
            except Exception as exc:
                logger.warning(
                    "[%s] finish payload validation failed: %s", self.name, exc,
                )
                # 关键：validator 失败时**不**设置 _captured_decision，让外层
                # 循环继续，LLM 在下一轮收到错误说明的 tool_result 后可以
                # 自己修正参数后重新调用 finish 工具。否则 _captured_decision
                # 会带着 {"_raw": ..., "_error": ...} 这种残废 payload 退出
                # 循环，上层 NodeRuntime model_validate 时直接崩溃。
                return {
                    "ok": False,
                    "error": str(exc),
                    "hint": (
                        f"你刚才调用 {self.finish.name} 的参数未通过 schema "
                        "校验。请仔细阅读上面的 error 信息，补全或修正缺失/"
                        "不合法的字段后，重新调用一次该工具来结束本回合。"
                    ),
                }
            self._captured_decision = validated
            return {"ok": True}
        self._captured_decision = dict(payload)
        return {"ok": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _maybe_await(value: Any) -> None:
    if asyncio.iscoroutine(value):
        await value


def _has_result_for(results: list[dict[str, Any]], call_id: str) -> bool:
    """Whether ``results`` already contains a tool_result for ``call_id``."""
    if not call_id:
        return False
    for blk in results:
        if blk.get("type") == "tool_result" and str(blk.get("id") or "") == call_id:
            return True
    return False


def _collect_pending_tool_use_ids(memory: Memory) -> list[tuple[str, str]]:
    """Find tool_use blocks in the last assistant msg that have no matching
    tool_result yet. Returns list of (call_id, tool_name).

    Used to repair a broken memory state (e.g. when acting was interrupted)
    so the next LLM call doesn't 422 on unmatched tool_calls.
    """
    msgs = memory.get_memory()
    if not msgs:
        return []
    # Walk back: gather assistant tool_uses and tool_result ids since last
    # assistant. We only need to repair the very last assistant turn — older
    # broken states would have already been repaired or are too late to fix.
    last_assistant_idx: int | None = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].role == "assistant":
            last_assistant_idx = i
            break
    if last_assistant_idx is None:
        return []
    assistant = msgs[last_assistant_idx]
    tool_uses = assistant.get_content_blocks("tool_use") if hasattr(assistant, "get_content_blocks") else []
    if not tool_uses:
        return []
    # Tool results 在我们的 Msg 模型里是 SYSTEM-role 上挂 tool_result 块
    # (Msg.tool_results 实现)，所以这里按 block type 找而不是按 role 过滤。
    seen_ids: set[str] = set()
    for m in msgs[last_assistant_idx + 1:]:
        if not hasattr(m, "get_content_blocks"):
            continue
        for blk in m.get_content_blocks("tool_result"):
            cid = str(blk.get("id") or "")
            if cid:
                seen_ids.add(cid)
    pending: list[tuple[str, str]] = []
    for tu in tool_uses:
        cid = str(tu.get("id") or "")
        name = str(tu.get("name") or "")
        if cid and cid not in seen_ids:
            pending.append((cid, name))
    return pending


# Re-export so callers can do ``from app.runtime_core.runtime import ...``.
_ = MsgRole

__all__ = [
    "ConversationRuntime",
    "FinishConfig",
    "DEFAULT_FINISH_TOOL_NAME",
    "StreamEvent",
    "StreamSink",
]
