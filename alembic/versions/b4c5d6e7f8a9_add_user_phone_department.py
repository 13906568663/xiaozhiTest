"""add user phone and department

Revision ID: b4c5d6e7f8a9
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 用户管理界面早已展示/编辑这两个字段，本迁移补齐底层存储。
    op.add_column(
        "user_account",
        sa.Column("phone", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "user_account",
        sa.Column("department", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_account", "department")
    op.drop_column("user_account", "phone")
