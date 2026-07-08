"""add chatbot.vision_assist_model_code column

Revision ID: b3d5f7a9c1e2
Revises: a1c2e3d4f5b6
Create Date: 2026-06-16 14:50:00.000000

新增「视觉转写辅助模型」列：主模型不支持读图时，用该列指定的模型能力 code
（capability_registry.code，type=MODEL）把用户上传的图片先转写成文字再交给主模型。
为空表示不启用图片转写。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3d5f7a9c1e2"
down_revision: Union[str, Sequence[str], None] = "a1c2e3d4f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbot",
        sa.Column("vision_assist_model_code", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chatbot", "vision_assist_model_code")
