"""drop browser_extension capability type

移除「浏览器扩展」能力类型：

- 删除 capability_registry 中所有 type = browser_extension 的能力记录
- 将 capabilitytype CHECK 约束收敛为 MODEL / MCP / VIRTUAL_MCP / FUNCTION

Revision ID: b8c9d0e1f2a3
Revises: fa1b2c3d4e5f
Create Date: 2026-06-30 17:35:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "fa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
    "VIRTUAL_MCP",
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
    name="capabilitytype",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    bind = op.get_bind()
    capability_registry = sa.table(
        "capability_registry",
        sa.column("id", sa.String(length=36)),
        sa.column("type", sa.String(length=32)),
    )

    bind.execute(
        capability_registry.delete().where(
            capability_registry.c.type.in_(
                ("BROWSER_EXTENSION", "browser_extension"),
            ),
        )
    )

    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=OLD_CAPABILITY_TYPE,
            type_=NEW_CAPABILITY_TYPE,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=NEW_CAPABILITY_TYPE,
            type_=OLD_CAPABILITY_TYPE,
            existing_nullable=False,
        )
