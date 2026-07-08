"""add chatbot.skill_bindings column

把 SKILL.md 挂到 chatbot 上：chat_engine._build_node_definition 会把这一列
透传成 TaskNodeDefinition.skill_codes，CapabilityResolverService 在解析时
会把对应 SKILL.md 正文以 <available_skills> 块拼到 system prompt 末尾。

Revision ID: 34439afc1e7c
Revises: f9a1b2c3d4e6
Create Date: 2026-05-28 22:55:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "34439afc1e7c"
down_revision: Union[str, Sequence[str], None] = "f9a1b2c3d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbot",
        sa.Column(
            "skill_bindings",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbot", "skill_bindings")
