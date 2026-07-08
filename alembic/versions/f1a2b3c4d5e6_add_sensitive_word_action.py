"""add action column to sensitive_word_rule and action_taken to hit

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-04-14 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sensitive_word_rule",
        sa.Column(
            "action",
            sa.String(length=16),
            nullable=False,
            server_default="replace",
        ),
    )
    op.add_column(
        "sensitive_word_hit",
        sa.Column("action_taken", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensitive_word_hit", "action_taken")
    op.drop_column("sensitive_word_rule", "action")
