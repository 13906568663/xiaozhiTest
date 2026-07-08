"""add virtual_mcp capability type

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-14 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
    "FUNCTION",
    "BROWSER_EXTENSION",
    name="capabilitytype",
    native_enum=False,
    create_constraint=True,
)
NEW_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
    "VIRTUAL_MCP",
    "FUNCTION",
    "BROWSER_EXTENSION",
    name="capabilitytype",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=OLD_CAPABILITY_TYPE,
            type_=NEW_CAPABILITY_TYPE,
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    capability_registry = sa.table(
        "capability_registry",
        sa.column("id", sa.String(length=36)),
        sa.column("type", sa.String(length=32)),
    )
    bind.execute(
        capability_registry.delete().where(
            capability_registry.c.type.in_(("VIRTUAL_MCP", "virtual_mcp")),
        )
    )

    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=NEW_CAPABILITY_TYPE,
            type_=OLD_CAPABILITY_TYPE,
            existing_nullable=False,
        )
