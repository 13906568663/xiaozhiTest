"""migrate function capabilities to http api

Revision ID: e7b9d4f0f1c2
Revises: c8a5b8d90f2d
Create Date: 2026-03-24 17:15:00.000000

"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7b9d4f0f1c2"
down_revision: Union[str, Sequence[str], None] = "c8a5b8d90f2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MIGRATION_NOTE = (
    "Legacy local-function config is no longer supported. "
    "Reconfigure this Function capability as an HTTP API."
)


def _mark_legacy_function_config(config_json: Any, *, status: str) -> tuple[Any, bool]:
    if not isinstance(config_json, dict):
        return config_json, False
    if str(config_json.get("url") or "").strip():
        return config_json, False

    legacy_keys = {"entrypoint", "function_name", "preset_args", "preset_kwargs"}
    if not any(key in config_json for key in legacy_keys):
        return config_json, False

    next_config = dict(config_json)
    next_config.setdefault("migration_note", MIGRATION_NOTE)
    next_config.setdefault("legacy_status_before_http_migration", status)
    return next_config, True


def upgrade() -> None:
    bind = op.get_bind()
    capability_registry = sa.table(
        "capability_registry",
        sa.column("id", sa.String(length=36)),
        sa.column("type", sa.String(length=32)),
        sa.column("status", sa.String(length=32)),
        sa.column("config_json", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(
            capability_registry.c.id,
            capability_registry.c.status,
            capability_registry.c.config_json,
        ).where(capability_registry.c.type.in_(("FUNCTION", "function")))
    ).all()
    for capability_id, status, config_json in rows:
        next_config, changed = _mark_legacy_function_config(
            config_json,
            status=str(status or "active"),
        )
        if not changed:
            continue
        bind.execute(
            capability_registry.update()
            .where(capability_registry.c.id == capability_id)
            .values(
                status="disabled",
                config_json=next_config,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    capability_registry = sa.table(
        "capability_registry",
        sa.column("id", sa.String(length=36)),
        sa.column("type", sa.String(length=32)),
        sa.column("status", sa.String(length=32)),
        sa.column("config_json", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(
            capability_registry.c.id,
            capability_registry.c.config_json,
        ).where(capability_registry.c.type.in_(("FUNCTION", "function")))
    ).all()
    for capability_id, config_json in rows:
        if not isinstance(config_json, dict):
            continue
        if config_json.get("migration_note") != MIGRATION_NOTE:
            continue

        next_config = dict(config_json)
        previous_status = str(
            next_config.pop("legacy_status_before_http_migration", "active") or "active"
        )
        next_config.pop("migration_note", None)
        bind.execute(
            capability_registry.update()
            .where(capability_registry.c.id == capability_id)
            .values(
                status=previous_status,
                config_json=next_config,
            )
        )
