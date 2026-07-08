"""add wiki_space and wiki_page tables

Revision ID: a1b2c3d4e5f6
Revises: e0f1a2b3c4d5, f6a7b8c9d0e1
Create Date: 2026-04-21 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
# 合并仓库现存的两个 head（chatbot icon/status 与 audit_log result），
# 把 wiki 模块挂在统一新 head 之下。
down_revision: Union[str, Sequence[str], None] = (
    "e0f1a2b3c4d5",
    "f6a7b8c9d0e1",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wiki_space",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.UniqueConstraint("code", name="uq_wiki_space_code"),
    )
    op.create_index("ix_wiki_space_code", "wiki_space", ["code"], unique=False)

    op.create_table(
        "wiki_page",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["space_id"], ["wiki_space.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["wiki_page.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["user_account.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "space_id",
            "parent_id",
            "slug",
            name="uq_wiki_page_space_parent_slug",
        ),
    )
    op.create_index("ix_wiki_page_space_id", "wiki_page", ["space_id"])
    op.create_index("ix_wiki_page_parent_id", "wiki_page", ["parent_id"])
    op.create_index(
        "ix_wiki_page_space_parent_sort",
        "wiki_page",
        ["space_id", "parent_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_wiki_page_space_parent_sort", table_name="wiki_page")
    op.drop_index("ix_wiki_page_parent_id", table_name="wiki_page")
    op.drop_index("ix_wiki_page_space_id", table_name="wiki_page")
    op.drop_table("wiki_page")
    op.drop_index("ix_wiki_space_code", table_name="wiki_space")
    op.drop_table("wiki_space")
