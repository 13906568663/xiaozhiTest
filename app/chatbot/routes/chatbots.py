"""聊天机器人 CRUD REST API 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_current_user, require_permission
from app.db.models.iam import UserAccount
from app.db.session import get_db_session
from app.domain.enums import ChatbotType
from app.domain.permissions import PermissionCode
from app.chatbot.schemas import (
    ChatbotCreate,
    ChatbotDeleteResponse,
    ChatbotRead,
    ChatbotUpdate,
)
from app.chatbot.services import chatbots as chatbot_service

router = APIRouter()


def _to_read(bot, *, session_count: int | None = None) -> ChatbotRead:
    data = ChatbotRead.model_validate(bot)
    if session_count is not None:
        data.session_count = session_count
    else:
        data.session_count = len(bot.sessions) if bot.sessions else 0
    return data


@router.get(
    "",
    response_model=list[ChatbotRead],
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_READ))],
)
async def list_chatbots(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ChatbotRead]:
    items = await chatbot_service.list_chatbots(session)
    return [_to_read(item) for item in items]


@router.post(
    "",
    response_model=ChatbotRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def create_chatbot(
    payload: ChatbotCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserAccount, Depends(require_current_user)],
) -> ChatbotRead:
    data = payload.model_dump()
    data["type"] = ChatbotType.NORMAL
    data["goal_prompt"] = ""
    bot = await chatbot_service.create_chatbot(
        session,
        data,
        created_by=current_user.id,
    )
    await session.commit()
    await session.refresh(bot)
    return _to_read(bot, session_count=0)


@router.get(
    "/{chatbot_id}",
    response_model=ChatbotRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_READ))],
)
async def get_chatbot(
    chatbot_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatbotRead:
    bot = await chatbot_service.get_chatbot(session, chatbot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return _to_read(bot)


@router.put(
    "/{chatbot_id}",
    response_model=ChatbotRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def update_chatbot(
    chatbot_id: str,
    payload: ChatbotUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatbotRead:
    bot = await chatbot_service.update_chatbot(
        session, chatbot_id, payload.model_dump(exclude_unset=True)
    )
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    count = len(bot.sessions) if bot.sessions else 0
    await session.commit()
    await session.refresh(bot)
    return _to_read(bot, session_count=count)


@router.delete(
    "/{chatbot_id}",
    response_model=ChatbotDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def delete_chatbot(
    chatbot_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatbotDeleteResponse:
    deleted = await chatbot_service.delete_chatbot(session, chatbot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="机器人不存在")
    await session.commit()
    return ChatbotDeleteResponse(deleted=True, chatbot_id=chatbot_id)
