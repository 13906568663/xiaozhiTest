"""add embed_access table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-11 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embed_access",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("embed_token", sa.String(length=64), nullable=False),
        sa.Column("external_token", sa.Text(), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=True),
        sa.Column(
            "extra_json",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["template_id"], ["task_template.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_embed_access_embed_token",
        "embed_access",
        ["embed_token"],
        unique=True,
    )
    op.create_index(
        "ix_embed_access_external_user_id",
        "embed_access",
        ["external_user_id"],
    )
    op.create_index(
        "ix_embed_access_template_id",
        "embed_access",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_embed_access_template_id", table_name="embed_access")
    op.drop_index("ix_embed_access_external_user_id", table_name="embed_access")
    op.drop_index("ix_embed_access_embed_token", table_name="embed_access")
    op.drop_table("embed_access")
