"""知识库 REST API 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.knowledge.schemas import (
    ChunkSearchResult,
    DocumentDeleteResponse,
    DocumentRead,
    DocumentTextCreate,
    KnowledgeBaseCreate,
    KnowledgeBaseDeleteResponse,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.knowledge.services import knowledge_base as kb_service
from app.knowledge.services.file_parser import parse_file
from app.knowledge.services.retrieval import search_by_text

router = APIRouter()


# ---------------------------------------------------------------------------
# KnowledgeBase CRUD
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[KnowledgeBaseRead],
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_READ))],
)
async def list_knowledge_bases(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[KnowledgeBaseRead]:
    items = await kb_service.list_knowledge_bases(session)
    return [KnowledgeBaseRead.model_validate(item) for item in items]


@router.post(
    "",
    response_model=KnowledgeBaseRead,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeBaseRead:
    existing = await kb_service.get_knowledge_base_by_code(session, payload.code)
    if existing:
        raise HTTPException(
            status_code=400, detail=f"知识库编码 '{payload.code}' 已存在"
        )
    payload_data = payload.model_dump()
    try:
        payload_data["embedding_config"] = await kb_service.normalize_embedding_config(
            session, payload.embedding_config
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    kb = await kb_service.create_knowledge_base(session, payload_data)
    await session.commit()
    await session.refresh(kb)
    return KnowledgeBaseRead.model_validate(kb)


@router.get(
    "/{kb_id}",
    response_model=KnowledgeBaseRead,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_READ))],
)
async def get_knowledge_base(
    kb_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeBaseRead:
    kb = await kb_service.get_knowledge_base(session, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return KnowledgeBaseRead.model_validate(kb)


@router.put(
    "/{kb_id}",
    response_model=KnowledgeBaseRead,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeBaseRead:
    payload_data = payload.model_dump()
    try:
        payload_data["embedding_config"] = await kb_service.normalize_embedding_config(
            session, payload.embedding_config
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    kb = await kb_service.update_knowledge_base(session, kb_id, payload_data)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    await session.commit()
    await session.refresh(kb)
    return KnowledgeBaseRead.model_validate(kb)


@router.delete(
    "/{kb_id}",
    response_model=KnowledgeBaseDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def delete_knowledge_base(
    kb_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeBaseDeleteResponse:
    deleted = await kb_service.delete_knowledge_base(session, kb_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="知识库不存在")
    await session.commit()
    return KnowledgeBaseDeleteResponse(deleted=True, knowledge_base_id=kb_id)


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------


@router.get(
    "/{kb_id}/documents",
    response_model=list[DocumentRead],
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_READ))],
)
async def list_documents(
    kb_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[DocumentRead]:
    docs = await kb_service.list_documents(session, kb_id)
    return [DocumentRead.model_validate(doc) for doc in docs]


@router.post(
    "/{kb_id}/documents/text",
    response_model=DocumentRead,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def create_document_from_text(
    kb_id: str,
    payload: DocumentTextCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentRead:
    kb = await kb_service.get_knowledge_base(session, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    doc = await kb_service.create_document_from_text(
        session,
        kb_id=kb_id,
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
    )
    await session.commit()
    await session.refresh(doc)
    return DocumentRead.model_validate(doc)


@router.post(
    "/{kb_id}/documents/upload",
    response_model=DocumentRead,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def upload_document(
    kb_id: str,
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentRead:
    kb = await kb_service.get_knowledge_base(session, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        parse_result = await parse_file(file_bytes, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not parse_result.content.strip():
        raise HTTPException(status_code=400, detail="文件解析后内容为空")

    title = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
    doc = await kb_service.create_document_from_text(
        session,
        kb_id=kb_id,
        title=title,
        content=parse_result.content,
        source_type=parse_result.source_type,
        file_name=file.filename,
        file_size=len(file_bytes),
        metadata=parse_result.metadata,
    )
    await session.commit()
    await session.refresh(doc)
    return DocumentRead.model_validate(doc)


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    response_model=DocumentDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def delete_document(
    kb_id: str,
    doc_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentDeleteResponse:
    deleted = await kb_service.delete_document(session, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    await session.commit()
    return DocumentDeleteResponse(deleted=True, document_id=doc_id)


@router.post(
    "/{kb_id}/documents/{doc_id}/reindex",
    response_model=DocumentRead,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_WRITE))],
)
async def reindex_document(
    kb_id: str,
    doc_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentRead:
    try:
        doc = await kb_service.reindex_document(session, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(doc)
    return DocumentRead.model_validate(doc)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.post(
    "/{kb_id}/search",
    response_model=KnowledgeSearchResponse,
    dependencies=[Depends(require_permission(PermissionCode.KNOWLEDGE_READ))],
)
async def search_knowledge_base(
    kb_id: str,
    payload: KnowledgeSearchRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeSearchResponse:
    kb = await kb_service.get_knowledge_base(session, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    try:
        resolved_embedding_config = await kb_service.resolve_kb_embedding_config(
            session, kb
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    results = await search_by_text(
        session,
        knowledge_base_id=kb_id,
        query=payload.query,
        embedding_model=kb.embedding_model,
        embedding_config=resolved_embedding_config,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
    )

    return KnowledgeSearchResponse(
        query=payload.query,
        results=[
            ChunkSearchResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_title=r.document_title,
                chunk_index=r.chunk_index,
                content=r.content,
                score=r.score,
            )
            for r in results
        ],
        total=len(results),
    )
