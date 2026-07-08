"""小智 MCP 接入模块测试。

覆盖：
  - TaskBoard 任务登记 / 完成 / 失败 / 淘汰
  - ask_assistant 超时降级为后台任务，query_task 取回结果
  - WebSocket 桥接完整握手（假小智端：initialize -> tools/list -> tools/call）
  - 连接器断线自动重连
  - AgentProxy 会话粘滞（复用 / 空闲超时开新会话 / 会话失效开新会话）

测试遵循仓库惯例：sync test + asyncio.run(scenario())。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from websockets.asyncio.server import serve

from app.core.config import Settings
from app.chatbot.services.chat_engine import ChatEngine
from app.db.base import Base
from app.db.models.chatbot import Chatbot, ChatMessage
from app.domain.enums import ChatSessionStatus
from app.xiaozhi_mcp.agent_proxy import AgentProxy
from app.xiaozhi_mcp.bridge import serve_connection
from app.xiaozhi_mcp.connector import XiaozhiService
from app.xiaozhi_mcp.server import build_mcp_server
from app.xiaozhi_mcp.tasks import TaskBoard


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "xiaozhi_sync_timeout_seconds": 20.0,
        "xiaozhi_reply_max_chars": 800,
        "xiaozhi_session_idle_minutes": 30,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeProxy:
    """替身 AgentProxy：可配置回复延迟与内容。"""

    def __init__(self, reply: str = "已完成", delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay
        self.ask_calls: list[str] = []
        self.isolated_calls: list[str] = []

    async def ask(self, query: str) -> str:
        self.ask_calls.append(query)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.reply

    async def run_isolated(self, task_text: str) -> str:
        self.isolated_calls.append(task_text)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.reply


def _text_of(result: Any) -> str:
    """从 FastMCP call_tool 返回值中提取文本。

    工具带返回类型注解时 convert_result 产出 (非结构化内容, 结构化 dict)
    二元组，这里统一取非结构化部分拼接文本。
    """
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        result = result[0]
    if isinstance(result, (list, tuple)):
        return "".join(getattr(block, "text", "") for block in result)
    return str(result)


# ----------------------------------------------------------------------
# TaskBoard
# ----------------------------------------------------------------------


def test_task_board_lifecycle() -> None:
    async def scenario() -> None:
        board = TaskBoard(max_finished=2)

        async def ok() -> str:
            return "结果A"

        async def boom() -> str:
            raise RuntimeError("炸了")

        rec_ok = board.submit(ok(), description="任务A")
        rec_bad = board.submit(boom(), description="任务B")
        await asyncio.sleep(0.05)

        assert board.get(rec_ok.task_id) is not None
        assert board.get(rec_ok.task_id).status == "done"  # type: ignore[union-attr]
        assert board.get(rec_ok.task_id).result == "结果A"  # type: ignore[union-attr]
        assert board.get(rec_bad.task_id).status == "failed"  # type: ignore[union-attr]
        assert "炸了" in board.get(rec_bad.task_id).error  # type: ignore[union-attr]
        assert board.latest() is not None
        assert board.latest().task_id == rec_bad.task_id  # type: ignore[union-attr]

        # 淘汰：max_finished=2，再完成 2 个后最早完成的被清理
        r3 = board.submit(ok(), description="任务C")
        r4 = board.submit(ok(), description="任务D")
        await asyncio.sleep(0.05)
        assert board.get(r3.task_id) is not None
        assert board.get(r4.task_id) is not None
        remaining = [
            r
            for r in (rec_ok, rec_bad, r3, r4)
            if board.get(r.task_id) is not None
        ]
        assert len(remaining) == 2

        await board.shutdown()

    asyncio.run(scenario())


# ----------------------------------------------------------------------
# 元工具：超时降级 / 任务查询
# ----------------------------------------------------------------------


def test_ask_assistant_timeout_degrades_to_background_task() -> None:
    async def scenario() -> None:
        proxy = FakeProxy(reply="深度回答", delay=0.3)
        board = TaskBoard()
        settings = _make_settings(xiaozhi_sync_timeout_seconds=0.05)
        mcp = build_mcp_server(cast(AgentProxy, proxy), board, settings)

        result = await mcp.call_tool("ask_assistant", {"query": "复杂问题"})
        text = _text_of(result)
        assert "后台任务" in text

        record = board.latest()
        assert record is not None
        assert record.status == "running"

        # 等后台任务完成后用 query_task 取结果（默认查最近一个）
        for _ in range(50):
            if record.status != "running":
                break
            await asyncio.sleep(0.02)
        assert record.status == "done"

        query_result = await mcp.call_tool("query_task", {"task_id": 0})
        query_text = _text_of(query_result)
        assert "已完成" in query_text
        assert "深度回答" in query_text

        await board.shutdown()

    asyncio.run(scenario())


def test_ask_assistant_fast_path_and_submit_task() -> None:
    async def scenario() -> None:
        proxy = FakeProxy(reply="秒回")
        board = TaskBoard()
        settings = _make_settings(xiaozhi_sync_timeout_seconds=5.0)
        mcp = build_mcp_server(cast(AgentProxy, proxy), board, settings)

        text = _text_of(await mcp.call_tool("ask_assistant", {"query": "简单问题"}))
        assert text == "秒回"
        assert proxy.ask_calls == ["简单问题"]

        submit_text = _text_of(await mcp.call_tool("submit_task", {"task": "写周报"}))
        assert "已提交" in submit_text
        await asyncio.sleep(0.05)
        assert proxy.isolated_calls == ["写周报"]

        missing = _text_of(await mcp.call_tool("query_task", {"task_id": 999}))
        assert "没有找到" in missing

        await board.shutdown()

    asyncio.run(scenario())


# ----------------------------------------------------------------------
# WebSocket 桥接：假小智端完整握手
# ----------------------------------------------------------------------


def test_ws_bridge_handshake_and_tool_call() -> None:
    async def scenario() -> None:
        proxy = FakeProxy(reply="桥接回复")
        board = TaskBoard()
        mcp = build_mcp_server(cast(AgentProxy, proxy), board, _make_settings())

        transcript: dict[str, Any] = {}

        async def xiaozhi_handler(ws: Any) -> None:
            """模拟小智云端：在我们拨入的连接上扮演 MCP 客户端。"""
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "xiaozhi", "version": "1.0"},
                        },
                    }
                )
            )
            transcript["init"] = json.loads(await ws.recv())
            await ws.send(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            )
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
            transcript["tools"] = json.loads(await ws.recv())
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "ask_assistant",
                            "arguments": {"query": "你好"},
                        },
                    }
                )
            )
            transcript["call"] = json.loads(await ws.recv())
            await ws.close()

        async with serve(xiaozhi_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]  # type: ignore[index]
            await asyncio.wait_for(
                serve_connection(mcp, f"ws://127.0.0.1:{port}"), timeout=10
            )

        assert transcript["init"]["id"] == 1
        assert transcript["init"]["result"]["serverInfo"]["name"] == "agent-flow"

        tool_names = {t["name"] for t in transcript["tools"]["result"]["tools"]}
        assert tool_names == {"ask_assistant", "submit_task", "query_task"}

        call_content = transcript["call"]["result"]["content"]
        assert call_content[0]["text"] == "桥接回复"
        assert proxy.ask_calls == ["你好"]

        await board.shutdown()

    asyncio.run(scenario())


# ----------------------------------------------------------------------
# 连接器：断线重连
# ----------------------------------------------------------------------


def test_connector_reconnects_after_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr("app.xiaozhi_mcp.connector._BACKOFF_INITIAL", 0.05)

        connection_count = 0
        second_connection = asyncio.Event()

        async def xiaozhi_handler(ws: Any) -> None:
            nonlocal connection_count
            connection_count += 1
            if connection_count >= 2:
                second_connection.set()
            await ws.close()

        async with serve(xiaozhi_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]  # type: ignore[index]
            settings = _make_settings(
                xiaozhi_mcp_enabled=True,
                xiaozhi_mcp_endpoint=f"ws://127.0.0.1:{port}",
                xiaozhi_chatbot_id="",
            )
            service = XiaozhiService(settings)
            service.start()
            try:
                await asyncio.wait_for(second_connection.wait(), timeout=10)
            finally:
                await service.stop()

        assert connection_count >= 2

    asyncio.run(scenario())


# ----------------------------------------------------------------------
# AgentProxy：会话粘滞
# ----------------------------------------------------------------------


class FakeEngine:
    """替身 ChatEngine：只回显文本，不做 LLM 调用。"""

    async def handle_message(
        self,
        db_session: Any,
        chat_session: Any,
        user_content: str,
    ) -> tuple[ChatMessage, bool, None]:
        msg = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=f"回声：{user_content}",
            seq=1,
        )
        return msg, False, None


def test_agent_proxy_sticky_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        db_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
        )
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            bot = Chatbot(name="语音助手", system_prompt="简短口语化")
            db.add(bot)
            await db.commit()
            bot_id = bot.id

        monkeypatch.setattr(
            "app.xiaozhi_mcp.agent_proxy.SessionLocal", session_factory
        )

        settings = _make_settings(
            xiaozhi_chatbot_id=bot_id,
            xiaozhi_session_idle_minutes=30,
            xiaozhi_reply_max_chars=10,
        )
        proxy = AgentProxy(settings, engine=cast(ChatEngine, FakeEngine()))

        # 首次提问创建粘滞会话
        reply = await proxy.ask("第一句")
        assert reply.startswith("回声：第一句"[:10])
        first_session = proxy._sticky_session_id
        assert first_session is not None

        # 第二次复用同一会话
        await proxy.ask("第二句")
        assert proxy._sticky_session_id == first_session

        # 空闲超时后自动开新会话
        proxy._last_activity = time.monotonic() - 31 * 60
        await proxy.ask("第三句")
        second_session = proxy._sticky_session_id
        assert second_session != first_session

        # 会话被外部置为 COMPLETED 后也开新会话
        async with session_factory() as db:
            from app.db.models.chatbot import ChatSession as CS

            target = await db.get(CS, second_session)
            assert target is not None
            target.status = ChatSessionStatus.COMPLETED
            await db.commit()
        await proxy.ask("第四句")
        assert proxy._sticky_session_id != second_session

        # 截断：max 10 字符 + 省略标记
        long_reply = await proxy.ask("第五句非常长的内容测试截断逻辑")
        assert long_reply.endswith("……（内容过长，已截断）")

        await db_engine.dispose()

    asyncio.run(scenario())
