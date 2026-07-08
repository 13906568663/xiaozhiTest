"""drop virtual_mcp capability type

动态工具集（DynamicTool）功能已下线，virtual_mcp 类型的能力条目无法再解析：

- 删除 capability_registry 中所有 type = virtual_mcp 的能力记录
- 将 capabilitytype CHECK 约束收敛为 MODEL / MCP / FUNCTION

Revision ID: c4d5e6f7a8b0
Revises: a3b4c5d6e7f8
Create Date: 2026-07-05 01:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b0"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
    "VIRTUAL_MCP",
    "FUNCTION",
    name="capabilitytype",
    native_enum=False,
    create_constraint=True,
)
NEW_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "MCP",
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
            capability_registry.c.type.in_(("VIRTUAL_MCP", "virtual_mcp")),
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
