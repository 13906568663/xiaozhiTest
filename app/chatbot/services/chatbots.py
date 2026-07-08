"""Chatbot CRUD 服务。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.chatbot import Chatbot
from app.domain.enums import ChatbotType


async def list_chatbots(session: AsyncSession) -> list[Chatbot]:
    stmt = (
        sa.select(Chatbot)
        .where(Chatbot.type != ChatbotType.EMBED)
        .options(selectinload(Chatbot.sessions))
        .order_by(Chatbot.created_at.desc())
    )
    return list((await session.scalars(stmt)).unique().all())


async def get_chatbot(session: AsyncSession, chatbot_id: str) -> Chatbot | None:
    stmt = (
        sa.select(Chatbot)
        .where(Chatbot.id == chatbot_id)
        .options(selectinload(Chatbot.sessions))
    )
    return (await session.scalars(stmt)).unique().one_or_none()


async def create_chatbot(
    session: AsyncSession,
    data: dict,
    *,
    created_by: str | None = None,
) -> Chatbot:
    chatbot = Chatbot(**data, created_by=created_by)
    session.add(chatbot)
    await session.flush()
    return chatbot


async def update_chatbot(
    session: AsyncSession,
    chatbot_id: str,
    data: dict,
) -> Chatbot | None:
    chatbot = await get_chatbot(session, chatbot_id)
    if chatbot is None:
        return None
    for key, value in data.items():
        if value is not None:
            setattr(chatbot, key, value)
    await session.flush()
    return chatbot


async def delete_chatbot(session: AsyncSession, chatbot_id: str) -> bool:
    chatbot = await get_chatbot(session, chatbot_id)
    if chatbot is None:
        return False
    await session.delete(chatbot)
    await session.flush()
    return True
