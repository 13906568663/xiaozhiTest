"""记忆存储 CRUD 服务。"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import MemoryStore

logger = logging.getLogger(__name__)


async def list_memory_stores(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    memory_type: str | None = None,
    keyword: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[MemoryStore], int]:
    filters: list[sa.ColumnElement[bool]] = []
    if user_id is not None:
        filters.append(MemoryStore.user_id == user_id)
    if memory_type is not None:
        filters.append(MemoryStore.memory_type == memory_type)
    if keyword:
        like_pattern = f"%{keyword}%"
        filters.append(
            sa.or_(
                MemoryStore.content.ilike(like_pattern),
                MemoryStore.key.ilike(like_pattern),
                MemoryStore.username.ilike(like_pattern),
            )
        )
    where_clause = sa.and_(*filters) if filters else sa.true()
    base = sa.select(MemoryStore).where(where_clause)
    count_stmt = (
        sa.select(sa.func.count()).select_from(MemoryStore).where(where_clause)
    )
    total = int(await session.scalar(count_stmt) or 0)
    stmt = (
        base.order_by(MemoryStore.created_at.desc()).offset(skip).limit(limit)
    )
    items = list((await session.scalars(stmt)).all())
    return items, total


async def get_memory_store(session: AsyncSession, memory_id: str) -> MemoryStore | None:
    return await session.get(MemoryStore, memory_id)


async def create_memory_store(session: AsyncSession, data: dict[str, Any]) -> MemoryStore:
    row = MemoryStore(**data)
    session.add(row)
    await session.flush()
    return row


async def update_memory_store(
    session: AsyncSession,
    memory_id: str,
    data: dict[str, Any],
) -> MemoryStore | None:
    row = await get_memory_store(session, memory_id)
    if row is None:
        return None
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    await session.flush()
    return row


async def delete_memory_store(session: AsyncSession, memory_id: str) -> bool:
    row = await get_memory_store(session, memory_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def delete_memory_stores_for_user(session: AsyncSession, user_id: str) -> int:
    stmt = sa.select(MemoryStore).where(MemoryStore.user_id == user_id)
    rows = list((await session.scalars(stmt)).all())
    for row in rows:
        await session.delete(row)
    await session.flush()
    return len(rows)


async def persist_chat_memory(
    session: AsyncSession,
    *,
    user_id: str,
    username: str | None = None,
    session_id: str,
    user_content: str,
    assistant_content: str,
    turn: int,
) -> MemoryStore | None:
    """将一轮对话写入 memory_store，供记忆管理查阅。

    每轮写入一条，key 格式为 ``chat:{session_id}:turn:{turn}``。
    若已存在同 key 记录则跳过（幂等）。
    """
    key = f"chat:{session_id}:turn:{turn}"
    exists_stmt = (
        sa.select(sa.func.count())
        .select_from(MemoryStore)
        .where(MemoryStore.user_id == user_id, MemoryStore.key == key)
    )
    if (await session.scalar(exists_stmt) or 0) > 0:
        return None

    content = f"[用户] {user_content}\n\n[助手] {assistant_content}"
    try:
        row = MemoryStore(
            user_id=user_id,
            username=username,
            memory_type="short_term",
            key=key,
            content=content,
            metadata_json={
                "session_id": session_id,
                "turn": turn,
                "source": "chat_auto",
            },
        )
        session.add(row)
        await session.flush()
        return row
    except Exception:
        logger.warning("persist_chat_memory failed", exc_info=True)
        return None
