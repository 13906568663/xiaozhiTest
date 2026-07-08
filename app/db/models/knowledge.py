"""Knowledge 域 ORM 模型。

核心概念：
  - KnowledgeBase：知识库元数据，包含向量模型配置和分块策略。
  - KnowledgeDocument：知识库中的文档，记录原始内容和处理状态。
  - KnowledgeChunk：文档分块 + pgvector 向量，用于相似度检索。
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_type
from app.domain.enums import ChunkMethod, DocumentStatus


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """知识库注册表，管理向量模型配置和分块策略。"""

    __tablename__ = "knowledge_base"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), default="active")

    embedding_model: Mapped[str] = mapped_column(
        sa.String(128), default="text-embedding-3-small"
    )
    embedding_dimensions: Mapped[int] = mapped_column(sa.Integer, default=1536)
    embedding_config: Mapped[dict] = mapped_column(json_type, default=dict)

    chunk_method: Mapped[str] = mapped_column(
        sa.String(16), default=ChunkMethod.FIXED.value
    )
    chunk_size: Mapped[int] = mapped_column(sa.Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(sa.Integer, default=64)
    document_count: Mapped[int] = mapped_column(sa.Integer, default=0)

    documents: Mapped[list[KnowledgeDocument]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """知识库文档，存储解析后的纯文本及处理状态。"""

    __tablename__ = "knowledge_document"

    knowledge_base_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("knowledge_base.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(sa.String(256))
    source_type: Mapped[str] = mapped_column(sa.String(16), default="text")
    file_name: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    content: Mapped[str] = mapped_column(sa.Text(), default="")
    status: Mapped[DocumentStatus] = mapped_column(
        sa.Enum(
            DocumentStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=DocumentStatus.PENDING,
    )
    chunk_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(json_type, default=dict)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class KnowledgeChunk(UUIDPrimaryKeyMixin, Base):
    """文档分块 + pgvector 向量，用于相似度检索。

    knowledge_base_id 冗余存储以避免检索时 JOIN document 表。
    embedding 列的维度由知识库的 embedding_dimensions 决定，
    建表时不固定维度（使用 Vector(None)），由 HNSW 索引约束。
    """

    __tablename__ = "knowledge_chunk"

    document_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("knowledge_document.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("knowledge_base.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer)
    content: Mapped[str] = mapped_column(sa.Text())
    token_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    embedding = mapped_column(Vector(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(json_type, default=dict)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
