"""聊天引擎 — 用 ConversationRuntime 驱动多轮对话。

与工作流节点运行时不同，聊天引擎不涉及 session sleep/resume/compensation，
仅负责多轮对话、工具调用、以及流程机器人的目标判定。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.capabilities.schemas import ModelProviderConfig
from app.core.config import get_settings
from app.db.models.chatbot import Chatbot, ChatMessage, ChatSession
from app.domain.enums import ChatSessionStatus, ModelApiMode
from app.chatbot.services.session_memory import (
    build_memory_for_session,
    persist_session_memory,
)
from app.runtime_core.compression import CompressionConfig
from app.runtime_core.formatter import ChatFormatter
from app.runtime_core.hooks import HookRunner, HookStage
from app.runtime_core.memory import Memory
from app.runtime_core.messages import Msg, image_block, text_block
from app.runtime_core.plan import Plan, PlanNotebook, Subtask
from app.runtime_core.provider import OpenAICompatProvider
from app.runtime_core.runtime import ConversationRuntime, StreamEvent
from app.runtime_core.tool_protocol import ToolContext, ToolRegistry
from app.schemas.common import CapabilityBinding
from app.workflow.runtime.agent_hooks import register_audit_hooks
from app.workflow.runtime.helpers import (
    coerce_memory_compression_threshold,
    coerce_reasoning_effort,
)
from app.workflow.runtime.mcp_invoker import close_mcp_clients
from app.workflow.schemas import TaskNodeDefinition
from app.workflow.services.capability_resolver import CapabilityResolverService

logger = logging.getLogger(__name__)

_BASE64_IMG_RE = re.compile(r"!\[([^\]]*)\]\(data:image/[^)]+\)")
_DATA_IMG_FULL_RE = re.compile(r"!\[[^\]]*\]\((data:image/[^)]+)\)")
_FILE_DATA_URL_RE = re.compile(r"\n\n\[文件数据:[^\]]*\]\(data:[^)]+\)")
_LOCAL_IMG_RE = re.compile(r"!\[[^\]]*\]\((?!https?://|data:)[^)]+\)\n*")

_PLAN_UI_SYSTEM_HINT = (
    "## 计划工具使用规范（强约束）\n"
    "当任务需要多步骤执行（≥2 个明显可拆分的子任务）时，必须按以下顺序使用计划工具，"
    "计划进度会由系统界面单独展示给用户：\n"
    "1. **开始任务时**：调用 `plan_create(name, subtasks=[...])` 一次性列出全部子任务"
    "（每个子任务给出 name / description / expected_outcome）。\n"
    "2. **执行每个子任务前**：调用 `plan_update_subtask(index=i, state=\"in_progress\")` "
    "把当前步标记为执行中。\n"
    "3. **每个子任务完成后**：调用 `plan_update_subtask(index=i, state=\"done\", "
    "outcome=\"<一句话产出摘要>\")` 收尾，再开始下一步。\n"
    "4. **全部完成后**：调用 `plan_finish(outcome=\"<整体结论摘要>\")` 收官。\n"
    "5. **禁止**：调用了 `plan_create` 之后却**不**对任何子任务调用 `plan_update_subtask`"
    "——这会让用户在界面上看到「全部待执行」的假象。注意：这条禁止的是"
    "「不更新计划状态」，**不是**禁止在最终回复里输出实际产出——查询明细、"
    "样例数据、表格等交付物**必须**完整写进最终回复正文（见下方回复风格）。\n"
    "6. **子任务过多时**：若 `plan_create` 返回 `too many subtasks` 错误，请把列表"
    "合并到上限以内（默认上限会在错误信息里给出）后重新提交，不要忽略错误继续输出正文。\n"
    "7. **并行 tool_calls（强烈推荐，显著减少卡顿）**：当你需要在同一轮里同时"
    "「标记上一步 done」+「标记下一步 in_progress」+（可选）「触发该步的业务工具」时，"
    "请**在同一个 assistant 响应里一次性发出多个 tool_call**，而不是分多轮调用。"
    "典型示例：完成第 i 步后，下一条 assistant 应同时包含 "
    "`plan_update_subtask(i, done, outcome=...)`、"
    "`plan_update_subtask(i+1, in_progress)`、以及第 i+1 步真正要调用的业务工具——"
    "这样三件事一次 LLM 往返就完成，用户看到的「上一个 plan 已返回、下一个迟迟"
    "不来」的卡顿会消失。**禁止**把每个 plan 状态切换拆成独立一轮、中间什么都不做。\n"
    "8. **本轮无需 plan 时**：如果本轮**没有**调用过 `plan_create`（任务足够简单、"
    "一两步就能完成），**绝对不要**调用 `plan_finish` / `plan_update_subtask` / "
    "`plan_abandon` —— 这些工具只在已经存在活动 plan 时才有意义；直接输出回答即可。\n"
    "9. **收尾遗留 plan（重要）**：本轮开始时如果上下文里有上一轮遗留的活动 plan"
    "（顶层 state 仍是 `in_progress`，或仍有 `in_progress` 子任务），且该工作其实"
    "已经完成或不会继续，**先**把对应子任务更新为 `done`/`abandoned`（必要时附 outcome），"
    "再 `plan_finish` / `plan_abandon` 收官，**然后再**处理用户当前提问。否则用户界面"
    "会一直看到「执行中」的错误状态。系统已把上一轮的 plan 状态恢复进了当前 PlanNotebook，"
    "你可以直接对它调用更新工具，无需重新 `plan_create`。\n\n"
    "回复风格：计划卡片只向用户展示**进度**（每步状态 + 一句话 outcome），"
    "**不会**展示任何数据内容——`plan_update_subtask` 的 `outcome` 字段只渲染"
    "成一行摘要文字，用户在那里看不到表格或明细。因此：\n"
    "- **数据类交付物（查询明细、样例行、Markdown 表格、统计清单等）必须完整"
    "写在最终回复正文里**，绝不能只写进 outcome 字段就声称「已展示」——那样"
    "用户什么都看不到；\n"
    "- outcome 字段只写一句话进度摘要（如「已查到 82 条工单」），不要塞数据；\n"
    "- 不要把每一步计划状态重复成长段叙述，但关键结论、结果数据、下一步建议"
    "必须保留在正文中。"
)


def _strip_base64_images(text: str) -> str:
    """Replace inline base64 image markdown with a compact placeholder."""
    text = _BASE64_IMG_RE.sub(r"[\1: 图片已发送给用户]", text)
    text = _FILE_DATA_URL_RE.sub("", text)
    return text


def _strip_local_image_refs(text: str) -> str:
    """Remove markdown images that reference local file paths."""
    return _LOCAL_IMG_RE.sub("", text).strip()


def _split_user_content_to_blocks(text: str) -> list[dict[str, Any]]:
    """If *text* contains ``![…](data:image/…)`` markdown images, split it
    into runtime_core blocks so vision-capable models receive the images.
    """
    images: list[str] = _DATA_IMG_FULL_RE.findall(text)
    if not images:
        return [text_block(text)] if text else []

    text_only = _DATA_IMG_FULL_RE.sub("", text).strip()
    blocks: list[dict[str, Any]] = []
    if text_only:
        blocks.append(text_block(text_only))
    for url in images:
        blocks.append(image_block(url=url))
    return blocks


class ChatEngine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.capability_resolver = CapabilityResolverService()

    async def _resolve_node(
        self, db_session: AsyncSession, bot: Chatbot,
    ) -> TaskNodeDefinition:
        node_def = self._build_node_definition(bot)
        # ChatEngine 走"按需加载"的 SKILL.md 注入策略：system_prompt 只暴露索引，
        # 由 register_skill_loader 注册的 load_skill 工具在 LLM 显式调用时再拉
        # 正文。workflow 节点维持旧的"一次性全文注入"行为，二者通过该入参显式
        # 区分。
        return await self.capability_resolver.resolve_node_definition(
            db_session, node_def, progressive_skills=True,
        )

    @staticmethod
    async def _bump_session_activity(
        db_session: AsyncSession, chat_session: ChatSession,
    ) -> None:
        await db_session.execute(
            sa.update(ChatSession)
            .where(ChatSession.id == chat_session.id)
            .values(updated_at=sa.func.now())
        )

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        db_session: AsyncSession,
        chat_session: ChatSession,
        user_content: str,
    ) -> tuple[ChatMessage, bool, dict[str, Any] | None]:
        bot = chat_session.chatbot
        messages = list(chat_session.messages or [])
        next_seq = (messages[-1].seq + 1) if messages else 1

        user_msg = ChatMessage(
            session_id=chat_session.id,
            role="user",
            content=user_content,
            seq=next_seq,
        )
        db_session.add(user_msg)
        await db_session.flush()
        # 不在 ReAct loop 开始前 UPDATE chat_sessions —— 见 handle_message_stream
        # 同位置注释，避免持有行锁阻塞子专家。

        node_def = await self._resolve_node(db_session, bot)
        model_config = node_def.model.config if node_def.model else None

        # Memory 持久化：从 chat_session.context_json["memory"] 优先恢复（含
        # 上次压缩出的 summary 与 compressed mark），缺失时再退化到从
        # chat_message 全量重建。详见 session_memory 模块 docstring。
        memory = build_memory_for_session(chat_session, messages)

        turn_stats: dict[str, Any] = {}
        reply_text = await self._run_agent_turn(
            bot,
            node_def,
            messages,
            user_content,
            db_session,
            model_config=model_config,
            memory=memory,
            chat_session_id=chat_session.id,
            turn_stats=turn_stats,
        )

        usage_payload = turn_stats.get("usage")
        assistant_msg = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=reply_text,
            tool_calls_json=(
                [{"type": "turn_usage", "usage": usage_payload}]
                if usage_payload
                else []
            ),
            seq=next_seq + 1,
        )
        db_session.add(assistant_msg)
        await db_session.flush()
        await self._bump_session_activity(db_session, chat_session)

        # 跟着路由层的 commit 一起把 Memory 状态合并写回 context_json["memory"]：
        # 用 SQL 级 JSONB 合并避免覆盖同一行的 plan / embed_* 等其它键。短链路
        # commit 几乎瞬时，不会和子专家长事务争行锁。
        await persist_session_memory(
            chat_session.id,
            memory,
            last_message_seq=assistant_msg.seq,
            session=db_session,
        )

        goal_achieved = False
        goal_result = None

        if bot.goal_prompt:
            from app.chatbot.services.goal_judge import GoalJudge

            judge = GoalJudge()
            all_messages = messages + [user_msg, assistant_msg]
            goal_achieved, goal_result = await judge.judge(
                bot, all_messages, model_config=model_config,
            )

            if goal_achieved:
                chat_session.status = ChatSessionStatus.COMPLETED
                chat_session.result_json = goal_result or {}
                await db_session.flush()

        current_turn = (next_seq + 1) // 2
        if not goal_achieved and bot.max_turns and current_turn >= bot.max_turns:
            chat_session.status = ChatSessionStatus.EXPIRED
            await db_session.flush()

        return assistant_msg, goal_achieved, goal_result

    async def handle_message_stream(
        self,
        db_session: AsyncSession,
        chat_session: ChatSession,
        user_content: str,
        *,
        request: Request | None = None,
        memory_user_id: str | None = None,
        memory_username: str | None = None,
        extra_tool_registrations: Any | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """流式处理用户消息。

        yield 的 kind:
        - ``delta``: 文本增量 (str)
        - ``thinking``: 推理增量 (str)，仅当模型返回 reasoning 内容
        - ``tool_call``: ``{id, name, arguments}``，模型决定调用一个工具
        - ``tool_result``: ``{id, tool_name, is_error, output}``，工具执行完
        - ``plan``: 计划状态更新 dict
        - ``done``: ChatResponse 字典
        - ``error``: 异常字符串
        """
        from app.chatbot.schemas import ChatMessageRead, ChatResponse

        bot = chat_session.chatbot
        messages = list(chat_session.messages or [])
        next_seq = (messages[-1].seq + 1) if messages else 1

        user_msg = ChatMessage(
            session_id=chat_session.id,
            role="user",
            content=user_content,
            seq=next_seq,
        )
        db_session.add(user_msg)
        await db_session.flush()
        # 注意：故意不在此处 UPDATE chat_sessions（_bump_session_activity）。
        # 该 UPDATE 会持有 chat_sessions 行锁直到最终 commit，期间整个 ReAct loop
        # （可能数十秒到数分钟）都把行锁住；当主 AI 调 run_subagent 工具，子专家
        # 在独立 SessionLocal 里 UPDATE chat_sessions.context_json[plan] 时会被
        # 阻塞，形成"主线程等子专家、子专家等行锁"的死锁。
        # updated_at 由 TimestampMixin 的 onupdate 钩子在最终短事务（assistant_msg
        # 落库时）自动刷新；如果该轮没有任何 chat_sessions 字段变更，则在最终
        # commit 前显式调用 _bump_session_activity 触发 UPDATE。

        node_def = await self._resolve_node(db_session, bot)
        model_config = node_def.model.config if node_def.model else None

        # 同步链路一致：从 context_json["memory"] 恢复 Memory，让上一轮
        # 压缩出的 summary 与 compressed mark 跨请求复用，避免每次都从
        # chat_message 重塞文本。
        memory = build_memory_for_session(chat_session, messages)

        # 统一事件队列：(kind, data)
        event_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        plan_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        turn_stats: dict[str, Any] = {}
        task = asyncio.create_task(
            self._run_agent_turn(
                bot,
                node_def,
                messages,
                user_content,
                db_session,
                model_config=model_config,
                event_queue=event_queue,
                plan_queue=plan_queue,
                extra_tool_registrations=extra_tool_registrations,
                memory=memory,
                chat_session_id=chat_session.id,
                turn_stats=turn_stats,
            )
        )

        last_stream_text = ""
        last_plan: dict[str, Any] | None = None
        tool_history: list[dict[str, Any]] = []

        async def _client_disconnected() -> bool:
            if request is None:
                return False
            return await request.is_disconnected()

        def _consume_event(kind: str, data: Any) -> tuple[str, Any] | None:
            nonlocal last_stream_text
            if kind == "delta":
                last_stream_text += data
                return ("delta", data)
            if kind in ("thinking", "tool_call", "tool_result"):
                if kind == "tool_call" and isinstance(data, dict):
                    tool_history.append({
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "arguments": data.get("arguments"),
                    })
                elif kind == "tool_result" and isinstance(data, dict):
                    tool_history.append({
                        "id": data.get("id"),
                        "name": data.get("tool_name"),
                        "is_error": data.get("is_error"),
                        "output": data.get("output"),
                        "type": "result",
                    })
                return (kind, data)
            return None

        try:
            while not task.done():
                if await _client_disconnected():
                    await db_session.rollback()
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return

                while True:
                    try:
                        plan = plan_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    last_plan = plan
                    yield ("plan", plan)

                try:
                    kind, data = await asyncio.wait_for(
                        event_queue.get(), timeout=0.08,
                    )
                except asyncio.TimeoutError:
                    continue
                emitted = _consume_event(kind, data)
                if emitted is not None:
                    yield emitted

            while True:
                try:
                    plan = plan_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                last_plan = plan
                yield ("plan", plan)

            while True:
                try:
                    kind, data = event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                emitted = _consume_event(kind, data)
                if emitted is not None:
                    yield emitted

            reply_text = await task
            reply_text = self._recover_stream_reply_text(
                reply_text, last_stream_text,
            )
        except asyncio.CancelledError:
            await db_session.rollback()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise
        except Exception as exc:
            await db_session.rollback()
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            yield ("error", str(exc))
            return

        tool_calls_payload: list[dict[str, Any]] = []
        if last_plan:
            tool_calls_payload.append({"type": "agent_plan", "plan": last_plan})
        if tool_history:
            tool_calls_payload.append({
                "type": "agent_actions",
                "actions": tool_history,
            })
        usage_payload = turn_stats.get("usage")
        if usage_payload:
            tool_calls_payload.append({
                "type": "turn_usage",
                "usage": usage_payload,
            })

        assistant_msg = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=reply_text,
            tool_calls_json=tool_calls_payload,
            seq=next_seq + 1,
        )
        db_session.add(assistant_msg)
        await db_session.flush()
        # 兜底刷新 updated_at（如果后续 goal/expired 分支未触发 chat_session 字段
        # 变更，TimestampMixin.onupdate 不会自动触发；显式发一次 UPDATE 让
        # 嵌入端的"最近活跃时间"列表保持准确）。此时已脱离 ReAct loop，行锁
        # 几乎瞬间释放，不会与子专家形成竞争。
        await self._bump_session_activity(db_session, chat_session)

        goal_achieved = False
        goal_result = None

        if bot.goal_prompt:
            from app.chatbot.services.goal_judge import GoalJudge

            judge = GoalJudge()
            all_messages = messages + [user_msg, assistant_msg]
            goal_achieved, goal_result = await judge.judge(
                bot, all_messages, model_config=model_config,
            )

            if goal_achieved:
                chat_session.status = ChatSessionStatus.COMPLETED
                chat_session.result_json = goal_result or {}
                await db_session.flush()

        current_turn = (next_seq + 1) // 2
        if not goal_achieved and bot.max_turns and current_turn >= bot.max_turns:
            chat_session.status = ChatSessionStatus.EXPIRED
            await db_session.flush()

        if memory_user_id:
            from app.memory.services import memories as memory_svc

            await memory_svc.persist_chat_memory(
                db_session,
                user_id=memory_user_id,
                username=memory_username,
                session_id=chat_session.id,
                user_content=user_content,
                assistant_content=reply_text,
                turn=current_turn,
            )

        await db_session.commit()
        await db_session.refresh(assistant_msg)

        # commit 之后再写 Memory：用独立短事务做 JSONB 字段级合并，避开
        # SSE 长事务可能持有的 chat_session 行写锁。即使持久化失败也只是
        # 下次会从 chat_message 兜底重建，不影响本轮回复。
        await persist_session_memory(
            chat_session.id,
            memory,
            last_message_seq=assistant_msg.seq,
        )

        payload = ChatResponse(
            message=ChatMessageRead.model_validate(assistant_msg),
            session_status=chat_session.status,
            goal_achieved=goal_achieved,
            goal_result=goal_result,
            usage=usage_payload,
        )
        yield ("done", payload.model_dump(mode="json"))

    @staticmethod
    def _recover_stream_reply_text(reply_text: str, streamed_text: str) -> str:
        """Keep useful streamed content when the final provider call fails."""
        if reply_text.startswith("对话生成失败：") and streamed_text.strip():
            return streamed_text.strip()
        return reply_text

    @staticmethod
    def _build_plan_notebook(
        plan_queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> PlanNotebook:
        plan_notebook = PlanNotebook(max_subtasks=12)
        if plan_queue is None:
            return plan_notebook

        async def emit_plan_change(
            _notebook: PlanNotebook,
            plan: Any,
        ) -> None:
            serialized_plan = ChatEngine._serialize_plan_event(plan)
            if serialized_plan is not None:
                await plan_queue.put(serialized_plan)

        plan_notebook.register_plan_change_hook(
            "chat_stream_plan", emit_plan_change,
        )
        return plan_notebook

    @staticmethod
    def _latest_plan_from_history(
        history: list[ChatMessage],
    ) -> dict[str, Any] | None:
        """从历史 assistant 消息的 tool_calls_json 里取最后一份 agent_plan。

        普通聊天模式下，``PlanNotebook`` 是按轮新建的、
        不跨轮持久化；上一轮模型如果忘了调 ``plan_finish`` 或漏掉某个子任务的
        ``done``，UI 上 plan 卡片就会一直停留在「执行中」。这里扫一遍历史，
        找到最近一次未结束的 plan 快照，交给 :meth:`_rehydrate_plan_notebook`
        塞回新 ``PlanNotebook.current_plan``，让本轮模型可以直接收尾。

        只取**最后一条** assistant 消息里的 ``agent_plan``：每轮 chat_engine
        都会把当前 plan 整份写回（参见 ``tool_calls_payload`` 的拼装位置），
        所以最近一条就是最新快照。已完结（state in done/abandoned）的 plan
        不再恢复——它对本轮没有可写意图，恢复反而会让模型误以为还能继续。
        """
        for msg in reversed(history):
            if (msg.role or "") != "assistant":
                continue
            # tool_calls_json 在 ORM 上声明为 list，但历史脏数据偶尔会落成 dict/null；
            # 这里用运行期 isinstance 兼容这两种异常情况（pyright 把它 narrow 成
            # list 后会认为多余，故 ignore）。
            raw_calls = msg.tool_calls_json
            calls: list[Any] = (
                list(raw_calls)
                if isinstance(raw_calls, list)  # pyright: ignore[reportUnnecessaryIsInstance]
                else []
            )
            for entry in calls:
                if (
                    isinstance(entry, dict)
                    and entry.get("type") == "agent_plan"
                    and isinstance(entry.get("plan"), dict)
                ):
                    plan = entry["plan"]
                    state = str(plan.get("state") or "").strip().lower()
                    if state in ("done", "abandoned"):
                        return None
                    return plan
            # 只要找到了一条 assistant 消息（不论它有无 agent_plan），就停止——
            # 再往前翻没有意义，更早的 plan 已经被这条更晚的快照覆盖。
            return None
        return None

    @staticmethod
    def _rehydrate_plan_notebook(
        plan_notebook: PlanNotebook,
        plan_dict: dict[str, Any],
    ) -> None:
        """把序列化 plan dict 还原回 PlanNotebook.current_plan。

        字段映射与 :func:`app.chatbot.services.plan_utils.serialize_plan` 对称
        （后者负责正向序列化，这里负责反向重建）。``id`` 保留原值，让前端能把
        新事件归并到同一张 plan 卡片上，避免重新画一张空白计划。
        """
        raw_subtasks = plan_dict.get("subtasks") or []
        if not isinstance(raw_subtasks, list):
            raw_subtasks = []
        subtasks: list[Subtask] = []
        for raw in raw_subtasks:
            if not isinstance(raw, dict):
                continue
            state = str(raw.get("state") or "todo").strip().lower()
            if state not in ("todo", "in_progress", "done", "abandoned"):
                state = "todo"
            outcome = raw.get("outcome")
            subtasks.append(
                Subtask(
                    name=str(raw.get("name") or "").strip(),
                    description=str(raw.get("description") or ""),
                    expected_outcome=str(raw.get("expected_outcome") or ""),
                    outcome=str(outcome) if outcome is not None else None,
                    state=state,
                )
            )
        plan_state = str(plan_dict.get("state") or "todo").strip().lower()
        if plan_state not in ("todo", "in_progress", "done", "abandoned"):
            plan_state = "todo"
        plan_outcome = plan_dict.get("outcome")
        plan_id = str(plan_dict.get("id") or "").strip()
        plan = Plan(
            name=str(plan_dict.get("name") or "执行计划"),
            description=str(plan_dict.get("description") or ""),
            expected_outcome=str(plan_dict.get("expected_outcome") or ""),
            outcome=str(plan_outcome) if plan_outcome is not None else None,
            state=plan_state,
            subtasks=subtasks,
        )
        if plan_id:
            plan.id = plan_id
        plan_notebook.current_plan = plan

    @staticmethod
    def _serialize_plan_event(plan: Any | None) -> dict[str, Any] | None:
        from app.chatbot.services.plan_utils import serialize_plan

        return serialize_plan(plan)

    # ------------------------------------------------------------------
    # Core: run one ReAct turn
    # ------------------------------------------------------------------

    async def _run_agent_turn(
        self,
        bot: Chatbot,
        node_def: TaskNodeDefinition,
        history: list[ChatMessage],
        user_content: str,
        db_session: AsyncSession,
        *,
        model_config: dict[str, Any] | None = None,
        event_queue: asyncio.Queue[tuple[str, Any]] | None = None,
        plan_queue: asyncio.Queue[dict[str, Any]] | None = None,
        extra_tool_registrations: Any | None = None,
        memory: Memory | None = None,
        chat_session_id: str | None = None,
        turn_stats: dict[str, Any] | None = None,
    ) -> str:
        """执行一轮 ReAct 对话，返回 assistant 回复文本。

        ``memory``: 调用方预先准备好的 :class:`Memory`（一般通过
        :func:`session_memory.build_memory_for_session` 构建，含上次压缩出的
        summary）；为 ``None`` 时退化到「当场用 ``history`` 文本重建」的旧行为
        ——主要用于尚未接入持久化的测试入口。

        ``turn_stats``: 可选的出参容器。传入 dict 时，本轮结束（含异常路径）会
        写入 ``turn_stats["usage"]``（:class:`TokenUsage` 的 dict 形态），供调用
        方落库 / 塞进响应。之所以用出参而不是改返回值，是为了不动既有两个调用
        点和测试的 ``-> str`` 契约。
        """
        from app.chatbot.services.builtin_tools import register_builtin_tools
        from app.workflow.runtime.tool_registry import (
            register_functions,
            register_knowledge_tools,
            register_mcps,
        )

        registry = ToolRegistry()
        register_builtin_tools(registry)
        connected_clients, _ = await register_mcps(
            registry, node_def, db_session=db_session,
        )
        register_functions(registry, node_def, {})
        if node_def.knowledges:
            register_knowledge_tools(registry, node_def, db_session=db_session)
        # 按需加载 SKILL.md 正文：仅在节点声明了 skill_codes 时注册 load_skill
        # 工具，配合 capability_resolver 的 progressive 注入模式（只放索引、不
        # 塞正文）。模型在索引匹配命中时主动调 load_skill(code) 拉取正文，未触
        # 发的技能正文不进上下文，省 token。
        skill_codes = getattr(node_def, "skill_codes", None) or []
        if skill_codes:
            from app.chatbot.services.skill_loader import register_skill_loader

            register_skill_loader(
                registry, db_session=db_session, skill_codes=skill_codes,
            )
        if extra_tool_registrations is not None:
            extra_tool_registrations(registry)

        plan_notebook = self._build_plan_notebook(plan_queue)
        if plan_notebook is not None:
            # 普通聊天模式跨轮恢复：上一轮模型可能漏调 plan_finish 或某个子任务
            # 的 plan_update_subtask(state="done")，把 plan 卡在「执行中」，
            # 这里从 history 里捞最近一份未完结快照塞回 current_plan，让本轮
            # 模型可以直接收尾，UI 上的 plan 卡片也能跟着更新。
            latest_plan = self._latest_plan_from_history(history)
            if latest_plan is not None:
                self._rehydrate_plan_notebook(plan_notebook, latest_plan)
            plan_notebook.register_tools(registry)

        if memory is None:
            # 调用方没有预构建（旧测试入口、潜在的脚本调用）。维持历史行为：
            # 直接按 chat_message 文本重建 Memory，但这条路径不会享受跨请求
            # 的压缩续接能力。新代码请使用 build_memory_for_session。
            memory = Memory()
            for msg in history:
                role = (
                    msg.role if msg.role in ("user", "assistant", "system") else "user"
                )
                content = msg.content or ""
                if content:
                    content = _strip_base64_images(content)
                memory.add_message(Msg(role, content))

        provider = self._build_provider(
            model_config, force_stream=event_queue is not None,
        )
        if provider is None:
            return "模型配置缺失，无法生成回复。请检查机器人的模型绑定配置。"

        runtime: ConversationRuntime | None = None

        async def on_stream(event: StreamEvent) -> None:
            if event_queue is None:
                return
            t = event.type
            if t == "text_delta":
                content = event.data.get("content")
                if isinstance(content, str) and content:
                    await event_queue.put(("delta", content))
            elif t == "thinking_delta":
                content = event.data.get("content")
                if isinstance(content, str) and content:
                    await event_queue.put(("thinking", content))
            elif t == "tool_call":
                await event_queue.put(("tool_call", dict(event.data)))
            elif t == "tool_result":
                await event_queue.put(("tool_result", dict(event.data)))

        try:
            sys_prompt = self._compose_sys_prompt(node_def)

            hook_runner = HookRunner()
            register_audit_hooks(hook_runner)
            # 工具调用日志埋点：写入 tool_call_log 表，供外部 API 调用统计接口
            # 查询。独立 session 写入，失败兜底（不抛），可通过
            # settings.tool_call_log_enabled 一键关闭。
            from app.chatbot.services.tool_call_logger import (
                make_tool_call_logger_hook,
            )
            hook_runner.register(
                HookStage.POST_ACTING,
                "tool_call_logger",
                make_tool_call_logger_hook(),
            )

            runtime = ConversationRuntime(
                provider=provider,
                registry=registry,
                memory=memory,
                formatter=self._build_formatter(model_config),
                hooks=hook_runner,
                compression=CompressionConfig(
                    enable=True,
                    trigger_threshold_tokens=self._memory_compression_threshold(
                        model_config,
                    ),
                    keep_recent=3,
                ),
                sys_prompt=sys_prompt,
                finish=None,
                max_iters=150,
                name=f"chatbot-{bot.id[:8]}",
                on_stream=on_stream if event_queue is not None else None,
            )

            cleaned = _FILE_DATA_URL_RE.sub("", user_content)
            input_blocks = _split_user_content_to_blocks(cleaned)
            input_msg = Msg("user", input_blocks)
            ctx = ToolContext(
                db_session=db_session,
                agent_id=bot.id,
                session_id=chat_session_id,
            )
            reply = await runtime.run_turn(input_msg, context=ctx)
            # 不能只取最后一条 assistant 消息的文本：模型经常把"交付物正文"
            # （明细表格 / 清单 / SQL）和 plan_update_subtask 等 tool_call 放在
            # 同一条中间消息里，最后一轮只剩一句"以上即为…"的收尾。只取最后
            # 一条会把正文整段丢掉（用户流式看到表格、落库后消失）。这里按
            # ReAct 迭代顺序拼接本轮全部 assistant 文本段，与流式输出一致。
            turn_texts = [
                t.strip() for t in runtime.last_turn_texts if t and t.strip()
            ]
            reply_text = (
                "\n\n".join(turn_texts)
                if turn_texts
                else reply.get_text_content()
            )

            return reply_text
        except Exception as exc:
            return f"对话生成失败：{exc}"
        finally:
            if runtime is not None:
                usage_dict = runtime.turn_usage.to_dict()
                if turn_stats is not None:
                    turn_stats["usage"] = usage_dict
                logger.info(
                    "[chat] turn usage session=%s bot=%s: %s",
                    chat_session_id, bot.id, usage_dict,
                )
            try:
                await provider.aclose()
            except Exception:
                pass
            await close_mcp_clients(connected_clients)

    # ------------------------------------------------------------------
    # Provider / formatter / config helpers
    # ------------------------------------------------------------------

    def _build_provider(
        self,
        model_binding: dict[str, Any] | None,
        *,
        force_stream: bool = False,
    ) -> OpenAICompatProvider | None:
        model_config = ModelProviderConfig.model_validate(model_binding or {})
        api_mode = model_config.api_mode
        if api_mode not in (
            ModelApiMode.OPENAI_COMPATIBLE,
            ModelApiMode.DEEPSEEK_COMPATIBLE,
        ):
            return None

        api_key = (
            model_config.api_key
            or (
                os.getenv(model_config.api_key_env)
                if model_config.api_key_env
                else None
            )
            or self.settings.openai_api_key
        )
        if not api_key:
            return None

        base_url = str(
            model_config.api_host or self.settings.openai_base_url or "https://api.openai.com/v1"
        ).strip()

        reasoning = coerce_reasoning_effort(model_config.reasoning_effort)
        extra_body: dict[str, Any] = {}
        if reasoning is None:
            extra_body["enable_thinking"] = False

        return OpenAICompatProvider(
            api_key=str(api_key),
            base_url=base_url,
            model=str(model_config.model_name or self.settings.default_model_name),
            max_tokens=int(model_config.max_tokens or 1024),
            stream=True if force_stream else bool(model_config.stream),
            reasoning_effort=reasoning,
            extra_body=extra_body or None,
            auth_header_name=model_config.auth_header_name,
            auth_header_scheme=model_config.auth_header_scheme,
        )

    @staticmethod
    def _build_formatter(model_binding: dict[str, Any] | None) -> ChatFormatter:
        model_config = ModelProviderConfig.model_validate(model_binding or {})
        return ChatFormatter(
            deepseek_compat=(
                model_config.api_mode == ModelApiMode.DEEPSEEK_COMPATIBLE
            ),
            promote_tool_result_images=True,
        )

    @staticmethod
    def _build_system_prompt(user_prompt: str | None) -> str:
        base_prompt = (user_prompt or "你是一个有帮助的助手。").strip()
        return f"{base_prompt}\n\n{_PLAN_UI_SYSTEM_HINT}"

    _WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

    @classmethod
    def _current_time_preamble(cls) -> str:
        """生成"当前权威时间"提示段，每轮重新注入到 system_prompt 顶部。

        历史教训：当前时间过去只能靠 ``get_current_time`` 工具按需获取——模型在
        某一轮拿到时间后，后续轮（尤其历史被压缩成摘要后）会复用历史里的旧时间
        当"现在"，导致跨天之后"今天/今晚/今天凌晨"仍解析成旧日期（实测会话
        7c7adffa 跨到 6/24 仍把"今天"当 6/18）。这里把权威 now 直接钉在提示词
        顶部、每个请求重算，并明确"历史中的时间不可当作现在"，从根上消除漂移。
        """
        try:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:  # noqa: BLE001 — 时区库异常时退化到本地时区，绝不可让组装提示词失败
            now = datetime.now(timezone.utc).astimezone()
        weekday = cls._WEEKDAY_ZH[now.weekday()]
        return (
            f"【当前系统时间】{now.strftime('%Y-%m-%d %H:%M:%S')} {weekday}"
            "（时区 Asia/Shanghai）。\n"
            "这是唯一权威的“现在”。对话历史与摘要中出现的任何时间都属于过去某轮，"
            "严禁当作当前时间；凡“今天 / 今晚 / 今天凌晨 / 明天 / 最近 N 天 / 本周”"
            "等相对时间，一律以上述当前时间为基准换算，不要复用历史里出现过的日期。\n\n"
        )

    @classmethod
    def _compose_sys_prompt(
        cls,
        node_def: TaskNodeDefinition,
    ) -> str:
        """组装最终交给 LLM 的 system_prompt。

        **必须从 ``node_def.prompt`` 取**——它由 ``CapabilityResolverService``
        生成，其中已经按当前模式（progressive / 全量）追加了
        ``<available_skills>`` 块等装载内容；如果直接用 ``bot.system_prompt``
        裸字段，resolver 注入的所有内容会被丢弃，``chatbot.skill_bindings``
        将永远不生效。这是修复历史上 skill 链路从未真正生效的 bug 的关键。

        在末尾追加 :data:`_PLAN_UI_SYSTEM_HINT`，注入 PlanNotebook 工具用法。
        """
        resolved_prompt = (node_def.prompt or "").strip()
        # 每轮把权威当前时间钉在最顶部，避免模型复用历史里的旧时间当"现在"。
        # 详见 _current_time_preamble。
        preamble = cls._current_time_preamble()
        return preamble + cls._build_system_prompt(resolved_prompt)

    @staticmethod
    def _memory_compression_threshold(model_binding: dict[str, Any] | None) -> int:
        model_config = ModelProviderConfig.model_validate(model_binding or {})
        return coerce_memory_compression_threshold(
            model_config.memory_compression_threshold,
        )

    @staticmethod
    def _build_node_definition(bot: Chatbot) -> TaskNodeDefinition:
        model_binding = None
        if bot.model_binding:
            model_binding = CapabilityBinding.model_validate(bot.model_binding)

        mcps = [CapabilityBinding.model_validate(b) for b in (bot.mcp_bindings or [])]
        functions = [
            CapabilityBinding.model_validate(b) for b in (bot.function_bindings or [])
        ]
        knowledges = [
            CapabilityBinding.model_validate(b) for b in (bot.knowledge_bindings or [])
        ]
        skill_codes = [
            str(code).strip()
            for code in (bot.skill_bindings or [])
            if isinstance(code, str) and code.strip()
        ]

        return TaskNodeDefinition(
            seq=1,
            code=f"chatbot-{bot.id[:8]}",
            name=bot.name,
            prompt=bot.system_prompt or "",
            model=model_binding,
            mcps=mcps,
            functions=functions,
            knowledges=knowledges,
            skill_codes=skill_codes,
        )
