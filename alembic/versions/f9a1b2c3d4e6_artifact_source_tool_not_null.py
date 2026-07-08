"""artifact source_tool_name not null

把 ``node_run_artifact.source_tool_name`` 从 ``NULL`` 收敛到空串：
Postgres 唯一约束对 NULL 列视为"互不相等"，会让同
``(node_run_id, content_sha256, artifact_type, NULL)`` 的 artifact 反复入库，
破坏 ``store_tool_output_as_artifact`` / ``offload_session_messages`` 的去重语义。
这里把历史 NULL 行回填为空串后，再加 NOT NULL DEFAULT '' 约束。

Revision ID: f9a1b2c3d4e6
Revises: e8f9a0b1c2d3
Create Date: 2026-05-28 18:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f9a1b2c3d4e6"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "node_run_artifact" not in inspector.get_table_names():
        return

    op.execute(
        "UPDATE node_run_artifact SET source_tool_name = '' WHERE source_tool_name IS NULL"
    )
    op.alter_column(
        "node_run_artifact",
        "source_tool_name",
        existing_type=sa.String(length=255),
        nullable=False,
        server_default="",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "node_run_artifact" not in inspector.get_table_names():
        return

    op.alter_column(
        "node_run_artifact",
        "source_tool_name",
        existing_type=sa.String(length=255),
        nullable=True,
        server_default=None,
    )
