"""add tool_call_log table

Revision ID: a7b8c9d0e1f2
Revises: e8f9a0b1c2d3
Create Date: 2026-06-02 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_call_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("tool_category", sa.String(length=32), nullable=False),
        sa.Column("http_method", sa.String(length=8), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "arguments_json",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("response_preview", sa.Text(), nullable=True),
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
            ["session_id"], ["chat_session.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_tool_call_log_created_at",
        "tool_call_log",
        ["created_at"],
    )
    op.create_index(
        "ix_tool_call_log_session_id",
        "tool_call_log",
        ["session_id"],
    )
    op.create_index(
        "ix_tool_call_log_tool_name",
        "tool_call_log",
        ["tool_name"],
    )
    op.create_index(
        "ix_tool_call_log_tool_category",
        "tool_call_log",
        ["tool_category"],
    )
    op.create_index(
        "ix_tool_call_log_is_success",
        "tool_call_log",
        ["is_success"],
    )
    # 复合索引：常见的「按时间窗 + 类目」「按 session + 时间」「按 name + 时间」三种查询模式
    op.create_index(
        "ix_tool_call_log_created_category",
        "tool_call_log",
        ["created_at", "tool_category"],
    )
    op.create_index(
        "ix_tool_call_log_session_created",
        "tool_call_log",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_tool_call_log_name_created",
        "tool_call_log",
        ["tool_name", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_call_log_name_created", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_session_created", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_created_category", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_is_success", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_tool_category", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_tool_name", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_session_id", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_created_at", table_name="tool_call_log")
    op.drop_table("tool_call_log")
