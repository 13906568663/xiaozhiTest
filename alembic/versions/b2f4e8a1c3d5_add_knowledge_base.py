"""add knowledge base tables and pgvector extension

Revision ID: b2f4e8a1c3d5
Revises: 9d1b6c7a8e90
Create Date: 2026-03-30 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "b2f4e8a1c3d5"
down_revision: Union[str, None] = "9d1b6c7a8e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_base",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "embedding_model",
            sa.String(128),
            nullable=False,
            server_default="text-embedding-3-small",
        ),
        sa.Column(
            "embedding_dimensions",
            sa.Integer(),
            nullable=False,
            server_default="1536",
        ),
        sa.Column("embedding_config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="512"),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default="64"),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.String(36),
            sa.ForeignKey("knowledge_base.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("file_name", sa.String(512), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.execute(
        """
        CREATE TABLE knowledge_chunk (
            id          VARCHAR(36) PRIMARY KEY,
            document_id VARCHAR(36) NOT NULL
                REFERENCES knowledge_document(id) ON DELETE CASCADE,
            knowledge_base_id VARCHAR(36) NOT NULL
                REFERENCES knowledge_base(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content     TEXT NOT NULL,
            token_count INTEGER,
            embedding   vector(1536),
            metadata_json JSONB NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index(
        "ix_knowledge_chunk_document_id",
        "knowledge_chunk",
        ["document_id"],
    )
    op.create_index(
        "ix_knowledge_chunk_knowledge_base_id",
        "knowledge_chunk",
        ["knowledge_base_id"],
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_chunk_embedding_hnsw
        ON knowledge_chunk
        USING hnsw (embedding vector_cosine_ops)
        """
    )

    # 插入知识库相关权限
    op.execute(
        """
        INSERT INTO permission (id, code, name, description, created_at, updated_at)
        VALUES
            (gen_random_uuid()::text, 'knowledge:read', '查看知识库', '允许查看知识库列表和详情', now(), now()),
            (gen_random_uuid()::text, 'knowledge:write', '管理知识库', '允许创建、编辑、删除知识库和文档', now(), now())
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM permission WHERE code IN ('knowledge:read', 'knowledge:write')"
    )
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_document")
    op.drop_table("knowledge_base")
