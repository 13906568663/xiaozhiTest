"""平台侧代理：把小智传来的自然语言请求路由到 ChatEngine。

职责：
  - 会话粘滞：为小智维持一个平台 ChatSession（多轮语音对话共享上下文），
    空闲超过 xiaozhi_session_idle_minutes 或会话不再 ACTIVE（目标达成 /
    轮次耗尽）时自动开新会话；
  - 串行化：同一粘滞会话上的 agent 轮次必须顺序执行（seq 递增、记忆写回
    都不允许并发），用进程内锁保证；
  - 隔离任务：submit_task 每次开独立新会话跑，不占粘滞会话的锁，长任务
    不阻塞正常对话；
  - 回复截断：语音播报场景限制返回文本长度。

DB 访问不走 FastAPI 依赖注入（连接器在请求作用域之外），直接用
SessionLocal 自管会话，模式与路由层一致：engine.handle_message 后 commit。
"""

from __future__ import annotations

import asyncio
import logging
import time

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chatbot.services.chat_engine import ChatEngine
from app.core.config import Settings, get_settings
from app.db.models.chatbot import Chatbot, ChatSession
from app.db.session import SessionLocal
from app.domain.enums import ChatbotStatus, ChatSessionStatus

logger = logging.getLogger("app.xiaozhi_mcp.agent_proxy")


class XiaozhiAgentError(RuntimeError):
    """配置或绑定问题导致无法执行（消息会直接播报给用户，保持简短）。"""


class AgentProxy:
    """小智请求 -> 平台 ChatEngine 的进程内代理。"""

    def __init__(
        self,
        settings: Settings | None = None,
        engine: ChatEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._engine = engine or ChatEngine()
        self._turn_lock = asyncio.Lock()
        self._sticky_session_id: str | None = None
        # time.monotonic()，进程内空闲计时；0 表示尚未有过对话
        self._last_activity: float = 0.0

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    async def describe_bot(self) -> str:
        """启动自检：校验绑定配置并返回机器人名称。"""
        async with SessionLocal() as db:
            bot = await self._get_bound_bot(db)
            return bot.name

    async def ask(self, query: str) -> str:
        """在粘滞会话上跑一轮完整 agent 对话，返回可播报的回复文本。

        同一会话的轮次串行；锁等待时间计入调用方的超时预算，超时由调用方
        （server.py 的降级逻辑）负责转后台。
        """
        async with self._turn_lock:
            async with SessionLocal() as db:
                chat_session = await self._acquire_sticky_session(db)
                reply = await self._run_turn(db, chat_session, query)
                self._last_activity = time.monotonic()
                return reply

    async def run_isolated(self, task_text: str) -> str:
        """在独立新会话中执行一次任务（不占粘滞会话、不参与串行锁）。

        任务描述需自包含（不带对话上下文），适合 submit_task 的长任务场景。
        """
        async with SessionLocal() as db:
            chat_session = await self._create_session(db)
            return await self._run_turn(db, chat_session, task_text)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _run_turn(
        self,
        db: AsyncSession,
        chat_session: ChatSession,
        text: str,
    ) -> str:
        assistant_msg, _goal_achieved, _goal_result = await self._engine.handle_message(
            db, chat_session, text
        )
        await db.commit()
        return self._clip(assistant_msg.content)

    def _clip(self, text: str) -> str:
        limit = max(1, self._settings.xiaozhi_reply_max_chars)
        cleaned = (text or "").strip()
        if not cleaned:
            return "（本轮没有产生文字回复）"
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit] + "……（内容过长，已截断）"

    async def _acquire_sticky_session(self, db: AsyncSession) -> ChatSession:
        """取回或新建粘滞会话。

        复用条件：距上次对话未超过空闲上限，且会话在库中仍是 ACTIVE
        （goal 判定 / max_turns 可能已把它置为 COMPLETED / EXPIRED）。
        """
        idle_limit_seconds = self._settings.xiaozhi_session_idle_minutes * 60
        if self._sticky_session_id is not None:
            idle = time.monotonic() - self._last_activity
            if idle <= idle_limit_seconds:
                existing = await self._load_session(db, self._sticky_session_id)
                if existing is not None and existing.status == ChatSessionStatus.ACTIVE:
                    return existing
            logger.info("小智粘滞会话 %s 失效或超时，开启新会话", self._sticky_session_id)
            self._sticky_session_id = None

        chat_session = await self._create_session(db)
        self._sticky_session_id = chat_session.id
        return chat_session

    @staticmethod
    async def _load_session(db: AsyncSession, session_id: str) -> ChatSession | None:
        stmt = (
            sa.select(ChatSession)
            .where(ChatSession.id == session_id)
            .options(
                selectinload(ChatSession.messages),
                selectinload(ChatSession.chatbot),
            )
        )
        return (await db.scalars(stmt)).unique().one_or_none()

    async def _get_bound_bot(self, db: AsyncSession) -> Chatbot:
        bot_id = (self._settings.xiaozhi_chatbot_id or "").strip()
        if not bot_id:
            raise XiaozhiAgentError("还没有绑定后台机器人，请先在服务端配置")
        bot = await db.get(Chatbot, bot_id)
        if bot is None:
            raise XiaozhiAgentError("绑定的后台机器人不存在，请检查服务端配置")
        if bot.status == ChatbotStatus.INACTIVE:
            raise XiaozhiAgentError("绑定的后台机器人已停用")
        return bot

    async def _create_session(self, db: AsyncSession) -> ChatSession:
        bot = await self._get_bound_bot(db)
        chat_session = ChatSession(
            chatbot_id=bot.id,
            status=ChatSessionStatus.ACTIVE,
        )
        db.add(chat_session)
        await db.commit()
        loaded = await self._load_session(db, chat_session.id)
        if loaded is None:  # pragma: no cover - 刚创建即消失只可能是外部删库
            raise XiaozhiAgentError("会话创建失败，请稍后重试")
        return loaded
