"""``chat_session.context_json`` 的字段级原子更新工具。

为什么需要它
------------
``ChatSession.context_json`` 同时被多条路径写：

1. SSE ``messages/stream`` 路由长事务里把 plan 写到 ``context_json["plan"]``；
2. 子专家（NodeRuntime）在独立 ``SessionLocal`` 里更新同一行的 plan 子键；
3. 接入方可选写入的会话归属信息（用户标识 / 模板 id / 标题 等元信息）；
4. 现在我们要追加的：``context_json["memory"]``（聊天主链路 Memory 持久化，
   见 :mod:`app.runtime_core.memory`）。

历史的 ORM "读改写" 模式（``ctx = dict(...); ctx[key] = ...; cs.context_json = ctx``）
在 SSE 长事务中会持有 ``chat_session`` 行写锁直到最终 commit，期间另一个独立
session 想更新同一行就会阻塞，表现为"流式卡住"——已经在
``app/workflow/services/task_context_ops.py`` 的 docstring 里详细解释过了。

本模块仿照那一套，对 ``chat_session`` 表使用 PostgreSQL JSONB 运算符做 key 级
UPDATE，不持有长锁，也不会"读改写"覆盖其他键。

非 PG 数据库不支持 ``||`` JSONB 运算符；agent-flow 的部署形态以 PG 为主，
此工具仅在 PG 上工作（与 ``task_context_ops`` 一致）。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.chatbot import ChatSession
from app.db.session import SessionLocal


_TABLE = ChatSession.__table__
_TABLE_REF = f'"{_TABLE.name}"'
_CTX_COL = "context_json"


_MERGE_SQL = sa.text(
    f"""
    UPDATE {_TABLE_REF}
       SET {_CTX_COL} = COALESCE({_CTX_COL}, '{{}}'::jsonb) || CAST(:patch AS jsonb)
     WHERE id = :sid
    """
)


_DELETE_KEY_SQL = sa.text(
    f"UPDATE {_TABLE_REF} SET {_CTX_COL} = COALESCE({_CTX_COL}, '{{}}'::jsonb) - :key WHERE id = :sid"
)


def _is_postgres(session: AsyncSession) -> bool:
    """看 session 绑定的 engine 是不是 PostgreSQL。

    SQLite/其它后端不支持 ``::jsonb`` / ``-`` JSONB 运算符，需要走 ORM
    "读改写" fallback。生产环境都是 PG，这条 fallback 主要服务于本仓库
    的 SQLite 测试夹具（``tests/backend/test_api_endpoints_smoke.py`` 等），
    让 chat 路由层不必为「换数据库」分两套代码。
    """
    try:
        return session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]
    except AttributeError:
        return False


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _run(session: AsyncSession | None, coro_factory) -> None:
    """优先用调用方已开的 session；否则开一条独立短事务并立即 commit。

    独立短事务路径用于"已经在 SSE 长事务外、需要绕过 ORM 单元的 commit"
    场景——比如 ReAct loop 跑完后写回 Memory 状态。这条路径绝不复用调用方
    可能正持锁的 session，避免互相阻塞。
    """
    if session is not None:
        await coro_factory(session)
        return
    async with SessionLocal() as own:
        await coro_factory(own)
        await own.commit()


async def _orm_merge_fallback(
    s: AsyncSession,
    chat_session_id: str,
    updates: dict[str, Any],
) -> None:
    """SQLite 等不支持 JSONB 运算符的后端走这条 ORM 路径（仅供测试）。

    并发安全性弱于 PG 路径——但测试场景没有真正的多事务并发 SSE 长锁，
    可以接受。
    """
    cs = await s.get(ChatSession, chat_session_id)
    if cs is None:
        return
    ctx = dict(cs.context_json or {})
    ctx.update(updates)
    cs.context_json = ctx
    flag_modified(cs, "context_json")
    await s.flush()


async def _orm_delete_fallback(
    s: AsyncSession,
    chat_session_id: str,
    keys: list[str],
) -> None:
    cs = await s.get(ChatSession, chat_session_id)
    if cs is None:
        return
    ctx = dict(cs.context_json or {})
    for key in keys:
        ctx.pop(key, None)
    cs.context_json = ctx
    flag_modified(cs, "context_json")
    await s.flush()


async def merge_context_keys(
    chat_session_id: str,
    updates: dict[str, Any],
    *,
    session: AsyncSession | None = None,
) -> None:
    """覆盖式合并若干键到 ``chat_session.context_json``。

    其它未在 ``updates`` 中出现的键不会被动到，不会发生"读改写"覆盖。
    """

    if not updates:
        return

    async def _do(s: AsyncSession) -> None:
        if _is_postgres(s):
            await s.execute(
                _MERGE_SQL,
                {"patch": _dumps(updates), "sid": chat_session_id},
            )
        else:
            await _orm_merge_fallback(s, chat_session_id, updates)

    await _run(session, _do)


async def delete_context_keys(
    chat_session_id: str,
    keys: Iterable[str],
    *,
    session: AsyncSession | None = None,
) -> None:
    """从 ``chat_session.context_json`` 删除若干键（JSONB ``-`` 运算符）。

    典型用例：``truncate_messages`` 删掉某 ``seq`` 之后的 chat_message 后，
    持久化的 ``memory`` 仍然引用着那些被删消息（包括 compressed_summary 也
    可能基于它们生成），需要把 ``"memory"`` 键整个删掉，让下次请求按剩余
    chat_message **从零重建** memory；同理 branch 出来的新会话也要删。
    """
    key_list = list(keys)
    if not key_list:
        return

    async def _do(s: AsyncSession) -> None:
        if _is_postgres(s):
            for key in key_list:
                await s.execute(_DELETE_KEY_SQL, {"key": key, "sid": chat_session_id})
        else:
            await _orm_delete_fallback(s, chat_session_id, key_list)

    await _run(session, _do)


__all__ = ["merge_context_keys", "delete_context_keys"]
