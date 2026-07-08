"""add chatbot.is_embed_default column (merge heads)

Revision ID: a1c2e3d4f5b6
Revises: a7b8c9d0e1f2, e0f1a2b3c4d5, f6a7b8c9d0e1, 34439afc1e7c
Create Date: 2026-06-08 14:50:00.000000

合并当时并行存在的多个 head，并新增「嵌入入口默认机器人」标记列。
全局至多一个 chatbot.is_embed_default = true（由 service 层保证唯一）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1c2e3d4f5b6"
down_revision: Union[str, Sequence[str], None] = (
    "a7b8c9d0e1f2",
    "e0f1a2b3c4d5",
    "f6a7b8c9d0e1",
    "34439afc1e7c",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        "ix_chatbot_is_embed_default",
        "chatbot",
        ["is_embed_default"],
    )


def downgrade() -> None:
    op.drop_index("ix_chatbot_is_embed_default", table_name="chatbot")
    op.drop_column("chatbot", "is_embed_default")
