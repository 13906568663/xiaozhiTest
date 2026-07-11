"""restore virtual_mcp capability type and dynamic_tool table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b0
Create Date: 2026-07-11 15:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
    "FUNCTION",
    name="capabilitytype",
    native_enum=False,
    create_constraint=True,
)
NEW_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
    "VIRTUAL_MCP",
    "FUNCTION",
    name="capabilitytype",
    native_enum=False,
    create_constraint=True,
)
JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=OLD_CAPABILITY_TYPE,
            type_=NEW_CAPABILITY_TYPE,
            existing_nullable=False,
        )

    op.create_table(
        "dynamic_tool",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "method",
            sa.String(length=16),
            nullable=False,
            server_default="POST",
        ),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("headers", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column(
            "parameters_schema",
            JSON_TYPE,
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_invoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    capability_registry = sa.table(
        "capability_registry",
        sa.column("type", sa.String(length=32)),
    )
    op.get_bind().execute(
        capability_registry.delete().where(
            capability_registry.c.type.in_(("VIRTUAL_MCP", "virtual_mcp"))
        )
    )

    op.drop_table("dynamic_tool")

    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=NEW_CAPABILITY_TYPE,
            type_=OLD_CAPABILITY_TYPE,
            existing_nullable=False,
        )
