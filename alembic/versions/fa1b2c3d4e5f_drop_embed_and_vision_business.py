"""drop embed/vision business schema

Revision ID: fa1b2c3d4e5f
Revises: c5e1a2b3d4f6
Create Date: 2026-06-30 00:00:00.000000

剥离业务定制后清理遗留 schema：
- 删除 embed_access 表（嵌入式聊天访问凭证）
- 删除 chatbot.is_embed_default 列（嵌入入口默认机器人标记）
- 删除 chatbot.vision_assist_model_code 列（视觉转写辅助模型）
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "fa1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "c5e1a2b3d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("chatbot", "vision_assist_model_code")
    op.drop_index("ix_chatbot_is_embed_default", table_name="chatbot")
    op.drop_column("chatbot", "is_embed_default")
    op.drop_index("ix_embed_access_template_id", table_name="embed_access")
    op.drop_index("ix_embed_access_external_user_id", table_name="embed_access")
    op.drop_index("ix_embed_access_embed_token", table_name="embed_access")
    op.drop_table("embed_access")


def downgrade() -> None:
    op.create_table(
        "embed_access",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("embed_token", sa.String(length=64), nullable=False),
        sa.Column("external_token", sa.Text(), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=True),
        sa.Column(
            "extra_json",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
            ["template_id"], ["task_template.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_embed_access_embed_token", "embed_access", ["embed_token"], unique=True
    )
    op.create_index(
        "ix_embed_access_external_user_id", "embed_access", ["external_user_id"]
    )
    op.create_index("ix_embed_access_template_id", "embed_access", ["template_id"])
    op.add_column(
        "chatbot",
        sa.Column(
            "is_embed_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_chatbot_is_embed_default", "chatbot", ["is_embed_default"]
    )
    op.add_column(
        "chatbot",
        sa.Column("vision_assist_model_code", sa.String(length=128), nullable=True),
    )
