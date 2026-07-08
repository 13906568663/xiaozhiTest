"""add chunk_method column to knowledge_base

Revision ID: c4d5e6f7a8b9
Revises: b2f4e8a1c3d5
Create Date: 2026-03-30 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b2f4e8a1c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_base",
        sa.Column(
            "chunk_method", sa.String(16), server_default="fixed", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_base", "chunk_method")
