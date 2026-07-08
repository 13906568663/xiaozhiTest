"""normalize chatbot type: flow -> normal

Revision ID: f0a1b2c3d4e5
Revises: d1e2f3a4b5c6
Create Date: 2026-03-31

"""

from typing import Sequence, Union

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE chatbot SET type = 'normal' WHERE type = 'flow'")


def downgrade() -> None:
    pass
