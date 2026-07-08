"""知识库 CRUD 与文档处理服务。"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.schemas import ModelProviderConfig
from app.db.base import generate_uuid
from app.db.models import CapabilityRegistry
from app.db.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.domain.enums import CapabilityType
from app.knowledge.schemas import EmbeddingConfig
from app.domain.enums import DocumentStatus
from app.knowledge.services.chunker import split_text, split_text_semantic
from app.knowledge.services.embedding import batch_embed

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KnowledgeBase CRUD
# ---------------------------------------------------------------------------


async def list_knowledge_bases(session: AsyncSession) -> list[KnowledgeBase]:
    stmt = sa.select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    result = await session.scalars(stmt)
    return list(result.all())


async def get_knowledge_base(session: AsyncSession, kb_id: str) -> KnowledgeBase | None:
    return await session.get(KnowledgeBase, kb_id)


async def get_knowledge_base_by_code(
    session: AsyncSession, code: str
) -> KnowledgeBase | None:
    stmt = sa.select(KnowledgeBase).where(KnowledgeBase.code == code)
    return await session.scalar(stmt)


async def normalize_embedding_config(
    session: AsyncSession, config_json: dict[str, Any] | None
) -> dict[str, Any]:
    """规范化 embedding_config，并在保存前校验 provider 引用是否存在。"""
    normalized = _normalize_embedding_config_payload(config_json)
    provider_ref = normalized.get("provider_ref")
    if provider_ref:
        provider = await _get_provider_capability(session, provider_ref)
        if provider is None:
            raise ValueError(f"Provider '{provider_ref}' 不存在，无法绑定到知识库。")
    return normalized


async def resolve_embedding_config(
    session: AsyncSession, config_json: dict[str, Any] | None
) -> dict[str, Any]:
    """解析知识库运行时 embedding 配置。

    如果配置了 provider_ref，则优先复用全局 Provider 中的 host / key / key_env，
    知识库自身只保留 embedding 侧的 api_path 和附加参数。
    """
    normalized = _normalize_embedding_config_payload(config_json)
    provider_ref = normalized.get("provider_ref")
    if not provider_ref:
        return normalized

    provider = await _get_provider_capability(session, provider_ref)
    if provider is None:
        raise ValueError(f"Provider '{provider_ref}' 不存在，请先修复知识库配置。")

    provider_config = ModelProviderConfig.model_validate(provider.config_json or {})
    resolved: dict[str, Any] = {}
    if provider_config.api_host:
        resolved["api_host"] = provider_config.api_host
    if provider_config.api_key:
        resolved["api_key"] = provider_config.api_key
    if provider_config.api_key_env:
        resolved["api_key_env"] = provider_config.api_key_env

    resolved.update(normalized)
    return resolved


async def resolve_kb_embedding_config(
    session: AsyncSession, kb: KnowledgeBase
) -> dict[str, Any]:
    return await resolve_embedding_config(session, kb.embedding_config)


async def create_knowledge_base(
    session: AsyncSession, data: dict[str, Any]
) -> KnowledgeBase:
    kb = KnowledgeBase(**data)
    session.add(kb)
    await session.flush()
    return kb


async def update_knowledge_base(
    session: AsyncSession, kb_id: str, data: dict[str, Any]
) -> KnowledgeBase | None:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        return None
    for key, value in data.items():
        setattr(kb, key, value)
    await session.flush()
    return kb


async def delete_knowledge_base(session: AsyncSession, kb_id: str) -> bool:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        return False
    await session.delete(kb)
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------


async def list_documents(session: AsyncSession, kb_id: str) -> list[KnowledgeDocument]:
    stmt = (
        sa.select(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_base_id == kb_id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get_document(session: AsyncSession, doc_id: str) -> KnowledgeDocument | None:
    return await session.get(KnowledgeDocument, doc_id)


async def create_document_from_text(
    session: AsyncSession,
    *,
    kb_id: str,
    title: str,
    content: str,
    source_type: str = "text",
    file_name: str | None = None,
    file_size: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> KnowledgeDocument:
    """创建文档并执行分块 + 向量化。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise ValueError(f"知识库 {kb_id} 不存在")

    doc = KnowledgeDocument(
        knowledge_base_id=kb_id,
        title=title,
        source_type=source_type,
        file_name=file_name,
        file_size=file_size or len(content.encode("utf-8")),
        content=content,
        status=DocumentStatus.PENDING,
        metadata_json=metadata or {},
    )
    session.add(doc)
    await session.flush()

    try:
        doc.status = DocumentStatus.PROCESSING
        await session.flush()

        resolved_embedding_config = await resolve_kb_embedding_config(session, kb)
        chunks = await _do_chunking(
            kb,
            content,
            source_type,
            embedding_config=resolved_embedding_config,
        )

        if not chunks:
            doc.status = DocumentStatus.READY
            doc.chunk_count = 0
            await session.flush()
            return doc

        chunk_texts = [c.content for c in chunks]
        vectors = await batch_embed(
            chunk_texts,
            model=kb.embedding_model,
            embedding_config=resolved_embedding_config,
        )

        for chunk_data, vector in zip(chunks, vectors):
            chunk = KnowledgeChunk(
                id=generate_uuid(),
                document_id=doc.id,
                knowledge_base_id=kb_id,
                chunk_index=chunk_data.index,
                content=chunk_data.content,
                token_count=_estimate_tokens(chunk_data.content),
                embedding=vector,
                metadata_json=chunk_data.metadata,
            )
            session.add(chunk)

        doc.status = DocumentStatus.READY
        doc.chunk_count = len(chunks)

        kb.document_count = await _count_documents(session, kb_id)
        await session.flush()

    except Exception:
        doc.status = DocumentStatus.FAILED
        doc.error_message = "文档处理失败，请检查 Embedding 服务配置"
        await session.flush()
        logger.exception("文档处理失败: doc_id=%s", doc.id)

    return doc


async def delete_document(session: AsyncSession, doc_id: str) -> bool:
    doc = await session.get(KnowledgeDocument, doc_id)
    if doc is None:
        return False
    kb_id = doc.knowledge_base_id
    await session.delete(doc)
    await session.flush()

    kb = await session.get(KnowledgeBase, kb_id)
    if kb:
        kb.document_count = await _count_documents(session, kb_id)
        await session.flush()
    return True


async def reindex_document(session: AsyncSession, doc_id: str) -> KnowledgeDocument:
    """重新索引文档：删除旧 chunks 并重新分块+向量化。"""
    doc = await session.get(KnowledgeDocument, doc_id)
    if doc is None:
        raise ValueError(f"文档 {doc_id} 不存在")

    await session.execute(
        sa.delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
    )
    await session.flush()

    kb = await session.get(KnowledgeBase, doc.knowledge_base_id)
    if kb is None:
        raise ValueError(f"知识库 {doc.knowledge_base_id} 不存在")

    doc.status = DocumentStatus.PROCESSING
    await session.flush()

    try:
        resolved_embedding_config = await resolve_kb_embedding_config(session, kb)
        chunks = await _do_chunking(
            kb,
            doc.content,
            doc.source_type,
            embedding_config=resolved_embedding_config,
        )

        if chunks:
            chunk_texts = [c.content for c in chunks]
            vectors = await batch_embed(
                chunk_texts,
                model=kb.embedding_model,
                embedding_config=resolved_embedding_config,
            )
            for chunk_data, vector in zip(chunks, vectors):
                chunk = KnowledgeChunk(
                    id=generate_uuid(),
                    document_id=doc.id,
                    knowledge_base_id=kb.id,
                    chunk_index=chunk_data.index,
                    content=chunk_data.content,
                    token_count=_estimate_tokens(chunk_data.content),
                    embedding=vector,
                    metadata_json=chunk_data.metadata,
                )
                session.add(chunk)

        doc.status = DocumentStatus.READY
        doc.chunk_count = len(chunks)
        doc.error_message = None
        await session.flush()

    except Exception as exc:
        doc.status = DocumentStatus.FAILED
        msg = str(exc).strip() if exc else ""
        doc.error_message = (msg[:500] if msg else None) or "重新索引失败"
        await session.flush()
        logger.exception("重新索引失败: doc_id=%s", doc_id)

    return doc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _do_chunking(
    kb: KnowledgeBase,
    content: str,
    source_type: str,
    *,
    embedding_config: dict[str, Any],
) -> list:
    """根据知识库的 chunk_method 选择切割策略。"""

    method = getattr(kb, "chunk_method", "fixed") or "fixed"
    if method == "semantic":
        return await split_text_semantic(
            content,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            embedding_model=kb.embedding_model,
            embedding_config=embedding_config,
        )
    return split_text(
        content,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        source_type=source_type,
        chunk_method="fixed",
    )


async def _count_documents(session: AsyncSession, kb_id: str) -> int:
    stmt = (
        sa.select(sa.func.count())
        .select_from(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_base_id == kb_id)
    )
    result = await session.scalar(stmt)
    return result or 0


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中英文混合：~1.5 字符/token）。"""
    return max(1, len(text) * 2 // 3)


def _normalize_embedding_config_payload(
    config_json: dict[str, Any] | None,
) -> dict[str, Any]:
    config = EmbeddingConfig.model_validate(config_json or {})
    normalized = config.model_dump(exclude_none=True)
    if normalized.get("provider_ref"):
        normalized.pop("api_host", None)
        normalized.pop("api_key", None)
        normalized.pop("api_key_env", None)
    return normalized


async def _get_provider_capability(
    session: AsyncSession, provider_ref: str
) -> CapabilityRegistry | None:
    stmt = (
        sa.select(CapabilityRegistry)
        .where(CapabilityRegistry.type == CapabilityType.MODEL)
        .where(CapabilityRegistry.code == provider_ref)
    )
    return await session.scalar(stmt)
