"""管理端会话管理视图 — 跨机器人的会话列表与统计。"""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.models.chatbot import Chatbot, ChatMessage, ChatSession
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.schemas.common import TimestampsMixin

router = APIRouter()


class AdminSessionItem(TimestampsMixin):
    """管理端会话列表条目。"""

    chatbot_id: str = Field(description="所属机器人 ID")
    chatbot_name: str | None = Field(default=None, description="机器人名称")
    status: str = Field(description="会话状态")
    message_count: int = Field(default=0, description="消息数量")
    title: str | None = Field(default=None, description="会话标题（取首条用户消息）")
    user: str | None = Field(
        default=None,
        description="会话所属用户标识；取自会话上下文，普通会话暂无",
    )
    user_name: str | None = Field(
        default=None,
        description="会话所属用户名；取自会话上下文，普通会话暂无",
    )


class AdminSessionListResponse(BaseModel):
    items: list[AdminSessionItem] = Field(default_factory=list)
    total: int = Field(default=0)


class AdminSessionDetail(AdminSessionItem):
    """管理端会话详情。"""

    context_json: dict = Field(default_factory=dict)
    result_json: dict = Field(default_factory=dict)


class AdminMessageItem(BaseModel):
    """管理端消息条目。"""

    id: str
    session_id: str
    role: str
    content: str
    content_truncated: bool = Field(default=False, description="content 是否被截断")
    seq: int
    created_at: str  # ISO format


class AdminMessageListResponse(BaseModel):
    items: list[AdminMessageItem] = Field(default_factory=list)
    total: int = Field(default=0)


@router.get(
    "",
    response_model=AdminSessionListResponse,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_MANAGE))],
)
async def list_admin_sessions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    chatbot_id: str | None = Query(default=None, description="按机器人 ID 筛选"),
    status: str | None = Query(default=None, description="按状态筛选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminSessionListResponse:
    """管理端：跨机器人分页查询所有会话。"""
    count_stmt = sa.select(sa.func.count()).select_from(ChatSession)
    if chatbot_id:
        count_stmt = count_stmt.where(ChatSession.chatbot_id == chatbot_id)
    if status:
        count_stmt = count_stmt.where(ChatSession.status == status)
    total = await session.scalar(count_stmt) or 0

    first_user_msg = (
        sa.select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id, ChatMessage.role == "user")
        .order_by(ChatMessage.seq.asc())
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    msg_count = (
        sa.select(sa.func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )

    stmt = (
        sa.select(
            ChatSession,
            Chatbot.name.label("chatbot_name"),
            first_user_msg.label("title"),
            msg_count.label("message_count"),
        )
        .outerjoin(Chatbot, Chatbot.id == ChatSession.chatbot_id)
    )
    if chatbot_id:
        stmt = stmt.where(ChatSession.chatbot_id == chatbot_id)
    if status:
        stmt = stmt.where(ChatSession.status == status)
    stmt = stmt.order_by(ChatSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)

    rows = (await session.execute(stmt)).all()
    items = []
    for chat_session, bot_name, session_title, m_count in rows:
        st = chat_session.status
        status_str = st.value if hasattr(st, "value") else str(st)
        ctx = chat_session.context_json or {}
        # context_json 里可选的会话归属信息（由接入方按需写入）
        user_identifier = ctx.get("user_id")
        user_name = ctx.get("user_name")
        items.append(
            AdminSessionItem(
                id=chat_session.id,
                created_at=chat_session.created_at,
                updated_at=chat_session.updated_at,
                chatbot_id=chat_session.chatbot_id,
                chatbot_name=bot_name,
                status=status_str,
                message_count=int(m_count or 0),
                title=session_title[:40] if session_title else None,
                user=str(user_identifier) if user_identifier else None,
                user_name=str(user_name) if user_name else None,
            )
        )
    return AdminSessionListResponse(items=items, total=total)


@router.get(
    "/{session_id}/messages",
    response_model=AdminMessageListResponse,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_MANAGE))],
)
async def list_admin_session_messages(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    content_max_length: int = Query(
        default=500, ge=0, le=100000,
        description="content 最大返回字符数，0 表示不截断",
    ),
) -> AdminMessageListResponse:
    """管理端：分页查看指定会话的消息，支持 content 截断以降低传输量。"""
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    count_stmt = (
        sa.select(sa.func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.session_id == session_id)
    )
    total = await session.scalar(count_stmt) or 0

    stmt = (
        sa.select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.seq)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = (await session.scalars(stmt)).all()

    items: list[AdminMessageItem] = []
    for m in messages:
        raw_content = m.content or ""
        truncated = False
        if content_max_length > 0 and len(raw_content) > content_max_length:
            raw_content = raw_content[:content_max_length]
            truncated = True
        items.append(
            AdminMessageItem(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=raw_content,
                content_truncated=truncated,
                seq=m.seq,
                created_at=m.created_at.isoformat() if m.created_at else "",
            )
        )
    return AdminMessageListResponse(items=items, total=total)
