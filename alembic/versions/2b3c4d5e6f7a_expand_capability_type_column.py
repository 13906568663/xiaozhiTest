"""expand capability_registry.type column to VARCHAR(32)

Previous length was VARCHAR(8) which was sized for 'function' (the longest
existing type). Adding 'browser_extension' (17 chars) requires expansion.

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "capability_registry",
        "type",
        existing_type=sa.String(8),
        type_=sa.String(32),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Only safe if no rows contain values longer than 8 chars
    op.alter_column(
        "capability_registry",
        "type",
        existing_type=sa.String(32),
        type_=sa.String(8),
        existing_nullable=False,
    )
