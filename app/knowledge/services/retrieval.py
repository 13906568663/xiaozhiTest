"""向量检索服务——基于 pgvector cosine 距离的相似度搜索。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.knowledge.services.embedding import embed_single

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    chunk_id: str
    document_id: str
    document_title: str
    chunk_index: int
    content: str
    score: float


async def search_knowledge_base(
    session: AsyncSession,
    *,
    knowledge_base_id: str,
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float | None = None,
) -> list[RetrievalResult]:
    """在指定知识库中执行向量相似度检索。

    score = 1 - cosine_distance，范围 [0, 1]，越高越相似。
    """
    distance_expr = KnowledgeChunk.embedding.cosine_distance(query_vector)

    stmt = (
        sa.select(
            KnowledgeChunk.id,
            KnowledgeChunk.document_id,
            KnowledgeDocument.title.label("document_title"),
            KnowledgeChunk.chunk_index,
            KnowledgeChunk.content,
            (1 - distance_expr).label("score"),
        )
        .join(
            KnowledgeDocument,
            KnowledgeChunk.document_id == KnowledgeDocument.id,
        )
        .where(
            KnowledgeChunk.knowledge_base_id == knowledge_base_id,
            KnowledgeChunk.embedding.is_not(None),
        )
        .order_by(distance_expr)
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    results: list[RetrievalResult] = []
    for row in rows:
        score = float(row.score)
        if score_threshold is not None and score < score_threshold:
            continue
        results.append(
            RetrievalResult(
                chunk_id=row.id,
                document_id=row.document_id,
                document_title=row.document_title,
                chunk_index=row.chunk_index,
                content=row.content,
                score=score,
            )
        )
    # 阈值过滤后仍保持按相似度从高到低（与 ORDER BY distance 一致，显式保证顺序）
    results.sort(key=lambda r: r.score, reverse=True)
    return results


async def search_by_text(
    session: AsyncSession,
    *,
    knowledge_base_id: str,
    query: str,
    embedding_model: str,
    embedding_config: dict,
    top_k: int = 5,
    score_threshold: float | None = None,
) -> list[RetrievalResult]:
    """文本检索：先向量化 query，再执行向量检索。"""
    query_vector = await embed_single(query, embedding_model, embedding_config)
    return await search_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        query_vector=query_vector,
        top_k=top_k,
        score_threshold=score_threshold,
    )
