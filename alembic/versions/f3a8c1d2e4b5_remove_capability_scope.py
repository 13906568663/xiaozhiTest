"""remove capability scope

Revision ID: f3a8c1d2e4b5
Revises: e7b9d4f0f1c2
Create Date: 2026-03-24 22:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a8c1d2e4b5"
down_revision: Union[str, Sequence[str], None] = "e7b9d4f0f1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CAPABILITY_SCOPE_ENUM = sa.Enum(
    "GLOBAL",
    "LOCAL",
    name="capabilityscope",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.drop_column("scope")


def downgrade() -> None:
    with op.batch_alter_table("capability_registry", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope",
                CAPABILITY_SCOPE_ENUM,
                nullable=False,
                server_default="GLOBAL",
            )
        )
