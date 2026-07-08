"""add session persistence to node run

Revision ID: 9d1b6c7a8e90
Revises: a6e2f9c1d4b7
Create Date: 2026-03-26 19:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d1b6c7a8e90"
down_revision: Union[str, Sequence[str], None] = "a6e2f9c1d4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "node_run",
        sa.Column("waiting_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "node_run",
        sa.Column(
            "session_memory_json",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "node_run",
        sa.Column(
            "session_messages_json",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "node_run",
        sa.Column(
            "runtime_state_json",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "node_run",
        sa.Column(
            "sleep_checkpoint_json",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "node_run",
        sa.Column(
            "compensation_config_json",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )

    op.execute(
        "UPDATE node_run SET session_memory_json = '{}' WHERE session_memory_json IS NULL"
    )
    op.execute(
        "UPDATE node_run SET session_messages_json = '[]' WHERE session_messages_json IS NULL"
    )
    op.execute(
        "UPDATE node_run SET runtime_state_json = '{}' WHERE runtime_state_json IS NULL"
    )
    op.execute(
        "UPDATE node_run SET sleep_checkpoint_json = '{}' WHERE sleep_checkpoint_json IS NULL"
    )
    op.execute(
        "UPDATE node_run SET compensation_config_json = '{}' WHERE compensation_config_json IS NULL"
    )


def downgrade() -> None:
    op.drop_column("node_run", "compensation_config_json")
    op.drop_column("node_run", "sleep_checkpoint_json")
    op.drop_column("node_run", "runtime_state_json")
    op.drop_column("node_run", "session_messages_json")
    op.drop_column("node_run", "session_memory_json")
    op.drop_column("node_run", "waiting_kind")
