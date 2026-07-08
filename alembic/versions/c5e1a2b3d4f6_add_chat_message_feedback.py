"""add chat_message feedback columns

Revision ID: c5e1a2b3d4f6
Revises: b3d5f7a9c1e2
Create Date: 2026-06-18 15:20:00.000000

新增聊天消息「反馈」两列，支撑外嵌智能体在 assistant 回复上点赞(👍)/点踩(👎)
并附文字意见：
  - feedback_rating  : SMALLINT，1=赞，-1=踩，NULL=未评价；
  - feedback_comment : TEXT，可选的文字意见。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c5e1a2b3d4f6"
down_revision: Union[str, Sequence[str], None] = "b3d5f7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("feedback_rating", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "chat_message",
        sa.Column("feedback_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "feedback_comment")
    op.drop_column("chat_message", "feedback_rating")
