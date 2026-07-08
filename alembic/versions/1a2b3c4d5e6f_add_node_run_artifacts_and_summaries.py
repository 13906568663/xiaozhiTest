"""add node run artifacts and summaries

Revision ID: 1a2b3c4d5e6f
Revises: f0a1b2c3d4e5
Create Date: 2026-04-02 11:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    node_run_columns = {
        column["name"] for column in inspector.get_columns("node_run")
    }

    if "last_turn_summary" not in node_run_columns:
        op.add_column(
            "node_run",
            sa.Column("last_turn_summary", sa.Text(), nullable=True),
        )
    if "last_tool_summary" not in node_run_columns:
        op.add_column(
            "node_run",
            sa.Column("last_tool_summary", sa.Text(), nullable=True),
        )
    if "artifact_count" not in node_run_columns:
        op.add_column(
            "node_run",
            sa.Column(
                "artifact_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if "session_message_count" not in node_run_columns:
        op.add_column(
            "node_run",
            sa.Column(
                "session_message_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "node_run_artifact" not in inspector.get_table_names():
        op.create_table(
            "node_run_artifact",
            sa.Column("node_run_id", sa.String(length=36), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("artifact_type", sa.String(length=32), nullable=False),
            sa.Column("source_tool_name", sa.String(length=255), nullable=True),
            sa.Column("preview_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("content_json", json_type, nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["node_run_id"], ["node_run.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "node_run_id",
                "content_sha256",
                "artifact_type",
                "source_tool_name",
                name="uq_node_run_artifact_content",
            ),
        )
        op.create_index(
            op.f("ix_node_run_artifact_node_run_id"),
            "node_run_artifact",
            ["node_run_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_node_run_artifact_node_run_id"), table_name="node_run_artifact")
    op.drop_table("node_run_artifact")
    op.drop_column("node_run", "session_message_count")
    op.drop_column("node_run", "artifact_count")
    op.drop_column("node_run", "last_tool_summary")
    op.drop_column("node_run", "last_turn_summary")
