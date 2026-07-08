"""ensure chatbot icon/status columns exist (repair skipped c9d0)

Revision ID: e0f1a2b3c4d5
Revises: f1a2b3c4d5e6
Create Date: 2026-04-14 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chatbot")}
    if "icon" not in cols:
        op.add_column(
            "chatbot",
            sa.Column(
                "icon",
                sa.String(32),
                nullable=False,
                server_default="🤖",
            ),
        )
    if "status" not in cols:
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
    pass
