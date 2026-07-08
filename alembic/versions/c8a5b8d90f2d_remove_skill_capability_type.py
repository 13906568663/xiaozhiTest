"""remove skill capability type

Revision ID: c8a5b8d90f2d
Revises: 8c5d9f6b2a31
Create Date: 2026-03-24 15:20:00.000000

"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8a5b8d90f2d"
down_revision: Union[str, Sequence[str], None] = "8c5d9f6b2a31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_CAPABILITY_TYPE = sa.Enum(
    "MODEL",
    "SKILL",
    "MCP",
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


def _strip_skill_keys(payload: Any) -> tuple[Any, bool]:
    if isinstance(payload, dict):
        changed = False
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "skills":
                changed = True
                continue
            cleaned_value, child_changed = _strip_skill_keys(value)
            cleaned[key] = cleaned_value
            changed = changed or child_changed
        return cleaned, changed

    if isinstance(payload, list):
        changed = False
        cleaned_items: list[Any] = []
        for item in payload:
            cleaned_item, child_changed = _strip_skill_keys(item)
            cleaned_items.append(cleaned_item)
            changed = changed or child_changed
        return cleaned_items, changed

    return payload, False


def _sanitize_json_column(bind: sa.engine.Connection, table_name: str, column_name: str) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.String(length=36)),
        sa.column(column_name, sa.JSON()),
    )

    rows = bind.execute(sa.select(table.c.id, table.c[column_name])).all()
    for row_id, payload in rows:
        cleaned_payload, changed = _strip_skill_keys(payload)
        if not changed:
            continue

        bind.execute(
            table.update()
            .where(table.c.id == row_id)
            .values(**{column_name: cleaned_payload})
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
            capability_registry.c.type.in_(("SKILL", "skill")),
        )
    )
    _sanitize_json_column(bind, "task_node", "config_json")
    _sanitize_json_column(bind, "task_template_version", "definition_json")

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
