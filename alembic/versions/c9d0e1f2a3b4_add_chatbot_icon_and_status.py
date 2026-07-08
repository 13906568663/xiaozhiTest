"""add chatbot icon and status columns

Revision ID: c9d0e1f2a3b4
Revises: e5f6a7b8c9d0
Create Date: 2026-04-14 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbot",
        sa.Column(
            "icon",
            sa.String(32),
            nullable=False,
            server_default="🤖",
        ),
    )
    op.add_column(
        "chatbot",
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbot", "status")
    op.drop_column("chatbot", "icon")
