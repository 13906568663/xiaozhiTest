"""drop wiki / menu_item / audit_log tables and chatbot.wiki_bindings

平台瘦身：聚焦智能体核心（对话引擎 + 机器人 + 模型/MCP 能力 + 技能/知识库/记忆），
下线维基、菜单管理、操作审计三个平台脚手架功能。

Revision ID: a3b4c5d6e7f8
Revises: b7c8d9e0f1a2
Create Date: 2026-07-05 01:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_wiki_page_space_parent_sort", table_name="wiki_page")
    op.drop_index("ix_wiki_page_parent_id", table_name="wiki_page")
    op.drop_index("ix_wiki_page_space_id", table_name="wiki_page")
    op.drop_table("wiki_page")
    op.drop_index("ix_wiki_space_code", table_name="wiki_space")
    op.drop_table("wiki_space")

    op.drop_index(op.f("ix_menu_item_parent_id"), table_name="menu_item")
    op.drop_index(op.f("ix_menu_item_code"), table_name="menu_item")
    op.drop_table("menu_item")

    op.drop_index(op.f("ix_audit_log_user_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_timestamp"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_column("chatbot", "wiki_bindings")


def downgrade() -> None:
    op.add_column(
        "chatbot",
        sa.Column(
            "wiki_bindings",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "result",
            sa.String(length=16),
            nullable=False,
            server_default="success",
        ),
        sa.Column("detail", JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_timestamp"), "audit_log", ["timestamp"], unique=False
    )
    op.create_index(
        op.f("ix_audit_log_user_id"), "audit_log", ["user_id"], unique=False
    )

    op.create_table(
        "menu_item",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("href", sa.String(length=255), nullable=True),
        sa.Column("permission", sa.String(length=128), nullable=True),
        sa.Column(
            "menu_type",
            sa.Enum(
                "GROUP",
                "ITEM",
                name="menuitemtype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("default_expanded", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["parent_id"], ["menu_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_item_code"), "menu_item", ["code"], unique=True)
    op.create_index(
        op.f("ix_menu_item_parent_id"), "menu_item", ["parent_id"], unique=False
    )

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
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
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
        sa.ForeignKeyConstraint(["space_id"], ["wiki_space.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["wiki_page.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["user_account.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "space_id", "parent_id", "slug", name="uq_wiki_page_space_parent_slug"
        ),
    )
    op.create_index("ix_wiki_page_space_id", "wiki_page", ["space_id"])
    op.create_index("ix_wiki_page_parent_id", "wiki_page", ["parent_id"])
    op.create_index(
        "ix_wiki_page_space_parent_sort",
        "wiki_page",
        ["space_id", "parent_id", "sort_order"],
    )
