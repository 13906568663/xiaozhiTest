"""聊天 API 路由（需认证，管理员在后台使用）。"""

import base64
import json
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_current_user, require_permission
from app.chatbot.schemas import (
    ChatFileUploadResult,
    ChatSessionBranchRequest,
    ChatMessageRead,
    ChatMessageSend,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionDeleteResponse,
    ChatSessionRead,
    ChatSessionSummaryRead,
    ChatSessionUpdate,
)
from app.chatbot.services.chat_engine import ChatEngine
from app.db.models.chatbot import Chatbot, ChatMessage, ChatSession
from app.db.session import get_db_session
from app.domain.enums import ChatbotStatus, ChatSessionStatus
from app.domain.permissions import PermissionCode
from app.iam.schemas import UserRead
from app.memory.services import memories as memory_service

router = APIRouter()
engine = ChatEngine()
SESSION_TITLE_FALLBACK = "新对话"
SESSION_MANUAL_TITLE_KEY = "manual_title"

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_DOCUMENT_CHARS = 50_000

_IMAGE_EXTENSIONS: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".gif": "gif",
    ".webp": "webp",
}

_DOCUMENT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".pdf", ".doc", ".docx", ".xlsx", ".html", ".htm", ".csv",
}

_ALL_SUPPORTED_EXTENSIONS = set(_IMAGE_EXTENSIONS.keys()) | _DOCUMENT_EXTENSIONS

_DOCUMENT_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


async def _handle_file_upload(file: UploadFile) -> ChatFileUploadResult:
    """处理单个文件上传：文档解析为文本，图片转为 base64 data URL。"""
    file_name = file.filename or "unknown"
    ext = PurePosixPath(file_name).suffix.lower()
    if ext not in _ALL_SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '{ext}'，支持：{', '.join(sorted(_ALL_SUPPORTED_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    file_size = len(file_bytes)
    if file_size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小 ({file_size / 1024 / 1024:.1f} MB) 超过限制 (10 MB)。",
        )

    if ext in _IMAGE_EXTENSIONS:
        mime_subtype = _IMAGE_EXTENSIONS[ext]
        b64 = base64.b64encode(file_bytes).decode("ascii")
        data_url = f"data:image/{mime_subtype};base64,{b64}"
        return ChatFileUploadResult(
            file_name=file_name,
            file_size=file_size,
            content_type="image",
            data_url=data_url,
        )

    from app.knowledge.services.file_parser import parse_file

    try:
        result = await parse_file(file_bytes, file_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    parsed_text = result.content
    if len(parsed_text) > _MAX_DOCUMENT_CHARS:
        parsed_text = parsed_text[:_MAX_DOCUMENT_CHARS] + "\n\n…（文档内容已截断）"

    mime = _DOCUMENT_MIME_TYPES.get(ext, "application/octet-stream")
    b64 = base64.b64encode(file_bytes).decode("ascii")
    file_data_url = f"data:{mime};base64,{b64}"

    return ChatFileUploadResult(
        file_name=file_name,
        file_size=file_size,
        content_type="document",
        parsed_text=parsed_text,
        file_data_url=file_data_url,
    )


@router.post(
    "/upload",
    response_model=ChatFileUploadResult,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def upload_chat_file(file: UploadFile) -> ChatFileUploadResult:
    """上传文件并解析，返回文档文本或图片 base64 data URL。"""
    return await _handle_file_upload(file)


def _normalize_session_text(value: str | None) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized or None


def _truncate_session_text(value: str | None, limit: int) -> str | None:
    normalized = _normalize_session_text(value)
    if normalized is None or len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _build_session_summary(
    chat_session: ChatSession,
    *,
    title_source: str | None = None,
    fallback_title_source: str | None = None,
    preview_source: str | None = None,
    message_count: int = 0,
) -> ChatSessionSummaryRead:
    manual_title = _truncate_session_text(
        (chat_session.context_json or {}).get(SESSION_MANUAL_TITLE_KEY), 40
    )
    title = (
        manual_title
        or _truncate_session_text(title_source, 40)
        or _truncate_session_text(fallback_title_source, 40)
        or SESSION_TITLE_FALLBACK
    )
    preview = _truncate_session_text(preview_source, 72)
    return ChatSessionSummaryRead(
        id=chat_session.id,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
        chatbot_id=chat_session.chatbot_id,
        status=chat_session.status,
        title=title,
        last_message_preview=preview,
        message_count=message_count,
    )


async def _load_session_with_counts(
    session: AsyncSession,
    session_id: str,
) -> tuple[ChatSession, str | None, str | None, str | None, int] | None:
    first_user_message = (
        sa.select(ChatMessage.content)
        .where(
            ChatMessage.session_id == ChatSession.id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.seq.asc())
        .limit(1)
        .scalar_subquery()
    )
    first_message = (
        sa.select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.seq.asc())
        .limit(1)
        .scalar_subquery()
    )
    last_message = (
        sa.select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.seq.desc())
        .limit(1)
        .scalar_subquery()
    )
    message_count = (
        sa.select(sa.func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .scalar_subquery()
    )
    stmt = sa.select(
        ChatSession,
        first_user_message.label("title_source"),
        first_message.label("fallback_title_source"),
        last_message.label("preview_source"),
        message_count.label("message_count"),
    ).where(ChatSession.id == session_id)
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    return (
        row[0],
        row[1],
        row[2],
        row[3],
        int(row[4] or 0),
    )


@router.get(
    "/sessions",
    response_model=list[ChatSessionSummaryRead],
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_READ))],
)
async def list_sessions(
    chatbot_id: Annotated[str, Query(description="机器人 ID")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: Annotated[
        ChatSessionStatus | None,
        Query(description="按状态筛选，不传则返回全部"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[ChatSessionSummaryRead]:
    """列出某机器人的会话，默认按更新时间倒序。"""
    bot = await session.get(Chatbot, chatbot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")

    first_user_message = (
        sa.select(ChatMessage.content)
        .where(
            ChatMessage.session_id == ChatSession.id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.seq.asc())
        .limit(1)
        .scalar_subquery()
    )
    first_message = (
        sa.select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.seq.asc())
        .limit(1)
        .scalar_subquery()
    )
    last_message = (
        sa.select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.seq.desc())
        .limit(1)
        .scalar_subquery()
    )
    message_count = (
        sa.select(sa.func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .scalar_subquery()
    )

    stmt = sa.select(
        ChatSession,
        first_user_message.label("title_source"),
        first_message.label("fallback_title_source"),
        last_message.label("preview_source"),
        message_count.label("message_count"),
    ).where(ChatSession.chatbot_id == chatbot_id)
    if status is not None:
        stmt = stmt.where(ChatSession.status == status)
    stmt = stmt.order_by(ChatSession.updated_at.desc()).limit(limit)

    rows = (await session.execute(stmt)).all()
    return [
        _build_session_summary(
            chat_session,
            title_source=title_source,
            fallback_title_source=fallback_title_source,
            preview_source=preview_source,
            message_count=int(item_count or 0),
        )
        for (
            chat_session,
            title_source,
            fallback_title_source,
            preview_source,
            item_count,
        ) in rows
    ]


@router.post(
    "/sessions",
    response_model=ChatSessionRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def create_session(
    payload: ChatSessionCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionRead:
    bot = await session.get(Chatbot, payload.chatbot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    if bot.status == ChatbotStatus.INACTIVE:
        raise HTTPException(status_code=400, detail="机器人已停用，无法创建新会话。")

    chat_session = ChatSession(
        chatbot_id=payload.chatbot_id,
        status=ChatSessionStatus.ACTIVE,
    )
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return ChatSessionRead.model_validate(chat_session)


@router.post(
    "/sessions/{session_id}/branch",
    response_model=ChatSessionRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def branch_session(
    session_id: str,
    payload: ChatSessionBranchRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionRead:
    source_stmt = (
        sa.select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(
            selectinload(ChatSession.messages),
            selectinload(ChatSession.chatbot),
        )
    )
    source_session = (await session.scalars(source_stmt)).unique().one_or_none()
    if source_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if source_session.chatbot.status == ChatbotStatus.INACTIVE:
        raise HTTPException(status_code=400, detail="机器人已停用，无法从本会话派生新会话。")

    # 拷贝 source 的 context_json，但**剥掉** memory 字段：分支会话只复制了
    # 部分前缀消息（before_seq 之前），如果把 source 的 memory 整段带过来，
    # memory 里会包含分支会话根本没有的后续消息（甚至 compressed_summary 也是
    # 基于完整 source 生成的），下次请求会让模型看到自己"没说过"的话。
    # 直接丢掉，让分支首次请求按拷贝过来的 chat_message 重建一份干净的 memory。
    branched_context = {
        k: v
        for k, v in (source_session.context_json or {}).items()
        if k != "memory"
    }
    branched_session = ChatSession(
        chatbot_id=source_session.chatbot_id,
        status=ChatSessionStatus.ACTIVE,
        context_json=branched_context,
        result_json={},
    )
    session.add(branched_session)
    await session.flush()

    copied_messages = [
        item
        for item in (source_session.messages or [])
        if payload.before_seq is None or item.seq < payload.before_seq
    ]
    for item in copied_messages:
        session.add(
            ChatMessage(
                session_id=branched_session.id,
                role=item.role,
                content=item.content,
                tool_calls_json=list(item.tool_calls_json or []),
                seq=item.seq,
            )
        )

    await session.commit()
    await session.refresh(branched_session)

    result = ChatSessionRead.model_validate(branched_session)
    result.message_count = len(copied_messages)
    return result


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_READ))],
)
async def get_session(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionRead:
    stmt = (
        sa.select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    chat_session = (await session.scalars(stmt)).unique().one_or_none()
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    result = ChatSessionRead.model_validate(chat_session)
    result.message_count = len(chat_session.messages)
    return result


@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionSummaryRead,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def update_session(
    session_id: str,
    payload: ChatSessionUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionSummaryRead:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 用 JSONB 字段级原子操作改 manual_title，避免和 SSE 长事务/独立 memory
    # 写入按整段 context_json "读改写"互相覆盖（详见 chat_context_ops 文档）。
    from app.chatbot.services.chat_context_ops import (
        delete_context_keys,
        merge_context_keys,
    )

    normalized_title = _normalize_session_text(payload.title)
    # 复用本路由 session 跑 JSONB UPDATE（不开独立短事务）：rename 路由本身
    # 不在 SSE 长事务里，没有"长锁"风险；走当前 session 的好处是测试夹具
    # 注入的 engine 一致，且和后续 _load_session_with_counts 共享一个事务。
    if normalized_title:
        await merge_context_keys(
            session_id,
            {SESSION_MANUAL_TITLE_KEY: normalized_title},
            session=session,
        )
    else:
        await delete_context_keys(
            session_id,
            [SESSION_MANUAL_TITLE_KEY],
            session=session,
        )
    await session.commit()

    # JSONB UPDATE 跳过了 ORM 单元，本路由 session 的 identity-map 还缓存
    # 着 ``chat_session`` 的旧 ``context_json``。下面 _load_session_with_counts
    # 的 SELECT 会从 identity-map 命中并返回 stale 数据，所以这里先 expire。
    session.expire(chat_session)

    row = await _load_session_with_counts(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    (
        loaded_session,
        title_source,
        fallback_title_source,
        preview_source,
        message_count,
    ) = row
    return _build_session_summary(
        loaded_session,
        title_source=title_source,
        fallback_title_source=fallback_title_source,
        preview_source=preview_source,
        message_count=message_count,
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=ChatSessionDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def delete_session(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionDeleteResponse:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    await session.delete(chat_session)
    await session.commit()
    return ChatSessionDeleteResponse(deleted=True, session_id=session_id)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessageRead],
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_READ))],
)
async def list_messages(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ChatMessageRead]:
    stmt = (
        sa.select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.seq)
    )
    messages = (await session.scalars(stmt)).all()
    return [ChatMessageRead.model_validate(m) for m in messages]


@router.post(
    "/sessions/{session_id}/messages/stream",
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def send_message_stream(
    request: Request,
    session_id: str,
    payload: ChatMessageSend,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_current_user)],
) -> StreamingResponse:
    stmt = (
        sa.select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(
            selectinload(ChatSession.messages),
            selectinload(ChatSession.chatbot),
        )
    )
    chat_session = (await session.scalars(stmt)).unique().one_or_none()
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if chat_session.status != ChatSessionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="会话已结束")
    if chat_session.chatbot.status == ChatbotStatus.INACTIVE:
        raise HTTPException(
            status_code=400,
            detail="机器人已停用，无法发送新消息。请先在对话配置中重新启用。",
        )

    async def event_gen():
        try:
            async for kind, data in engine.handle_message_stream(
                session, chat_session, payload.content,
                request=request,
                memory_user_id=current_user.id,
                memory_username=current_user.username,
            ):
                if kind == "delta":
                    line = json.dumps(
                        {"type": "delta", "text": data},
                        ensure_ascii=False,
                    )
                elif kind == "thinking":
                    line = json.dumps(
                        {"type": "thinking", "text": data},
                        ensure_ascii=False,
                    )
                elif kind == "tool_call":
                    line = json.dumps(
                        {"type": "tool_call", "tool": data},
                        ensure_ascii=False,
                    )
                elif kind == "tool_result":
                    line = json.dumps(
                        {"type": "tool_result", "tool": data},
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

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatResponse,
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def send_message(
    session_id: str,
    payload: ChatMessageSend,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_current_user)],
) -> ChatResponse:
    stmt = (
        sa.select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(
            selectinload(ChatSession.messages),
            selectinload(ChatSession.chatbot),
        )
    )
    chat_session = (await session.scalars(stmt)).unique().one_or_none()
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if chat_session.status != ChatSessionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="会话已结束")
    if chat_session.chatbot.status == ChatbotStatus.INACTIVE:
        raise HTTPException(
            status_code=400,
            detail="机器人已停用，无法发送新消息。请先在对话配置中重新启用。",
        )

    assistant_msg, goal_achieved, goal_result = await engine.handle_message(
        session, chat_session, payload.content
    )

    turn = (assistant_msg.seq + 1) // 2
    await memory_service.persist_chat_memory(
        session,
        user_id=current_user.id,
        username=current_user.username,
        session_id=session_id,
        user_content=payload.content,
        assistant_content=assistant_msg.content,
        turn=turn,
    )

    await session.commit()
    await session.refresh(assistant_msg)

    return ChatResponse(
        message=ChatMessageRead.model_validate(assistant_msg),
        session_status=chat_session.status,
        goal_achieved=goal_achieved,
        goal_result=goal_result,
    )


@router.delete(
    "/sessions/{session_id}",
    dependencies=[Depends(require_permission(PermissionCode.CHATBOTS_WRITE))],
)
async def close_session(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if chat_session.status == ChatSessionStatus.ACTIVE:
        chat_session.status = ChatSessionStatus.COMPLETED
        await session.commit()
    return {"closed": True, "session_id": session_id}
