"""add user api keys

Revision ID: 8c5d9f6b2a31
Revises: 5c8c4f5f6f7a
Create Date: 2026-03-21 16:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8c5d9f6b2a31"
down_revision: Union[str, Sequence[str], None] = "5c8c4f5f6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_api_key",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=255), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_api_key_key_prefix"), "user_api_key", ["key_prefix"], unique=True)
    op.create_index(op.f("ix_user_api_key_user_id"), "user_api_key", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_api_key_user_id"), table_name="user_api_key")
    op.drop_index(op.f("ix_user_api_key_key_prefix"), table_name="user_api_key")
    op.drop_table("user_api_key")
