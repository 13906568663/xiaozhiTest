"""公开聊天 API 路由（无需认证，通过 access_token 鉴权）。

供流程临时机器人使用，外部用户通过唯一链接访问。
"""

import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.chatbot import ChatSession
from app.db.session import get_db_session
from app.domain.enums import ChatSessionStatus
from app.chatbot.schemas import (
    ChatFileUploadResult,
    ChatMessageRead,
    ChatMessageSend,
    ChatResponse,
    PublicChatInfo,
)
from app.chatbot.services.chat_engine import ChatEngine

router = APIRouter()
engine = ChatEngine()


async def _get_valid_session(
    access_token: str,
    session: AsyncSession,
) -> ChatSession:
    """根据 access_token 加载会话，校验有效性。"""
    stmt = (
        sa.select(ChatSession)
        .where(ChatSession.access_token == access_token)
        .options(
            selectinload(ChatSession.messages),
            selectinload(ChatSession.chatbot),
        )
    )
    chat_session = (await session.scalars(stmt)).unique().one_or_none()
    if chat_session is None:
        raise HTTPException(status_code=404, detail="链接无效或已失效")

    if chat_session.expires_at and chat_session.expires_at < datetime.now(timezone.utc):
        if chat_session.status == ChatSessionStatus.ACTIVE:
            chat_session.status = ChatSessionStatus.EXPIRED
            await session.commit()
        raise HTTPException(status_code=410, detail="聊天会话已过期")

    return chat_session


@router.get("/{access_token}", response_model=PublicChatInfo)
async def get_public_chat_info(
    access_token: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PublicChatInfo:
    chat_session = await _get_valid_session(access_token, session)
    bot = chat_session.chatbot

    return PublicChatInfo(
        bot_name=bot.name,
        bot_description=bot.description,
        session_status=chat_session.status,
        messages=[ChatMessageRead.model_validate(m) for m in chat_session.messages],
    )


@router.post("/{access_token}/upload", response_model=ChatFileUploadResult)
async def upload_public_chat_file(
    access_token: str,
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatFileUploadResult:
    """公开聊天的文件上传：校验 access_token 后复用通用上传逻辑。"""
    await _get_valid_session(access_token, session)

    from app.chatbot.routes.chat import _handle_file_upload

    return await _handle_file_upload(file)


@router.post("/{access_token}/messages/stream")
async def send_public_message_stream(
    request: Request,
    access_token: str,
    payload: ChatMessageSend,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    chat_session = await _get_valid_session(access_token, session)

    if chat_session.status != ChatSessionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="聊天会话已结束")

    async def event_gen():
        goal_ok = False
        try:
            async for kind, data in engine.handle_message_stream(
                session, chat_session, payload.content, request=request
            ):
                if kind == "done":
                    payload_dict = data if isinstance(data, dict) else {}
                    goal_ok = bool(payload_dict.get("goal_achieved"))
                if kind == "delta":
                    line = json.dumps(
                        {"type": "delta", "text": data},
                        ensure_ascii=False,
                    )
                elif kind == "plan":
                    line = json.dumps(
                        {"type": "plan", "plan": data},
                        ensure_ascii=False,
                    )
                elif kind == "error":
                    line = json.dumps(
                        {"type": "error", "message": data},
                        ensure_ascii=False,
                    )
                else:
                    line = json.dumps(
                        {"type": "done", "payload": data},
                        ensure_ascii=False,
                    )
                yield f"data: {line}\n\n"
        except Exception as exc:
            err = json.dumps(
                {"type": "error", "message": str(exc)},
                ensure_ascii=False,
            )
            yield f"data: {err}\n\n"
            return
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{access_token}/messages", response_model=ChatResponse)
async def send_public_message(
    access_token: str,
    payload: ChatMessageSend,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatResponse:
    chat_session = await _get_valid_session(access_token, session)

    if chat_session.status != ChatSessionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="聊天会话已结束")

    assistant_msg, goal_achieved, goal_result = await engine.handle_message(
        session, chat_session, payload.content
    )
    await session.commit()
    await session.refresh(assistant_msg)

    return ChatResponse(
        message=ChatMessageRead.model_validate(assistant_msg),
        session_status=chat_session.status,
        goal_achieved=goal_achieved,
        goal_result=goal_result,
    )
