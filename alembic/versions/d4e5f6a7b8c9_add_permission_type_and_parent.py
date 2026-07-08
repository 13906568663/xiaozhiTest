"""add permission.type and permission.parent_id

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-13 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "permission",
        sa.Column("type", sa.String(10), nullable=False, server_default="API"),
    )
    op.add_column(
        "permission",
        sa.Column("parent_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_permission_parent_id",
        "permission",
        "permission",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_permission_parent_id", "permission", ["parent_id"])
    op.create_index("ix_permission_type", "permission", ["type"])


def downgrade() -> None:
    op.drop_index("ix_permission_type", table_name="permission")
    op.drop_index("ix_permission_parent_id", table_name="permission")
    op.drop_constraint("fk_permission_parent_id", "permission", type_="foreignkey")
    op.drop_column("permission", "parent_id")
    op.drop_column("permission", "type")
