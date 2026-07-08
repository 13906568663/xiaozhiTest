"""remove mcp tool_name config

Revision ID: a6e2f9c1d4b7
Revises: f3a8c1d2e4b5
Create Date: 2026-03-24 23:50:00.000000

"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a6e2f9c1d4b7"
down_revision: Union[str, Sequence[str], None] = "f3a8c1d2e4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _strip_mcp_tool_name_from_binding(binding: Any) -> tuple[Any, bool]:
    if not isinstance(binding, dict):
        return binding, False

    config = binding.get("config")
    if not isinstance(config, dict) or "tool_name" not in config:
        return binding, False

    next_binding = dict(binding)
    next_config = dict(config)
    next_config.pop("tool_name", None)
    next_binding["config"] = next_config
    return next_binding, True


def _strip_mcp_tool_name_from_node(node_payload: Any) -> tuple[Any, bool]:
    if not isinstance(node_payload, dict):
        return node_payload, False

    changed = False
    next_node = dict(node_payload)

    mcps = next_node.get("mcps")
    if isinstance(mcps, list):
        next_mcps: list[Any] = []
        for item in mcps:
            cleaned_item, item_changed = _strip_mcp_tool_name_from_binding(item)
            next_mcps.append(cleaned_item)
            changed = changed or item_changed
        next_node["mcps"] = next_mcps

    compensation = next_node.get("compensation")
    if isinstance(compensation, dict):
        action = compensation.get("action")
        if isinstance(action, dict) and str(action.get("type") or "").lower() == "mcp":
            cleaned_action, action_changed = _strip_mcp_tool_name_from_binding(action)
            if action_changed:
                next_compensation = dict(compensation)
                next_compensation["action"] = cleaned_action
                next_node["compensation"] = next_compensation
                changed = True

    return next_node, changed


def _sanitize_task_json(bind: sa.engine.Connection, table_name: str, column_name: str) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.String(length=36)),
        sa.column(column_name, sa.JSON()),
    )

    rows = bind.execute(sa.select(table.c.id, table.c[column_name])).all()
    for row_id, payload in rows:
        if not isinstance(payload, dict):
            continue

        changed = False
        next_payload = dict(payload)
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            next_nodes: list[Any] = []
            for node in nodes:
                cleaned_node, node_changed = _strip_mcp_tool_name_from_node(node)
                next_nodes.append(cleaned_node)
                changed = changed or node_changed
            next_payload["nodes"] = next_nodes
        else:
            next_payload, changed = _strip_mcp_tool_name_from_node(payload)

        if not changed:
            continue

        bind.execute(
            table.update().where(table.c.id == row_id).values(**{column_name: next_payload})
        )


def upgrade() -> None:
    bind = op.get_bind()
    capability_registry = sa.table(
        "capability_registry",
        sa.column("id", sa.String(length=36)),
        sa.column("type", sa.String(length=32)),
        sa.column("config_json", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(
            capability_registry.c.id,
            capability_registry.c.config_json,
        ).where(capability_registry.c.type.in_(("MCP", "mcp")))
    ).all()
    for capability_id, config_json in rows:
        if not isinstance(config_json, dict) or "tool_name" not in config_json:
            continue

        next_config = dict(config_json)
        next_config.pop("tool_name", None)
        bind.execute(
            capability_registry.update()
            .where(capability_registry.c.id == capability_id)
            .values(config_json=next_config)
        )

    _sanitize_task_json(bind, "task_node", "config_json")
    _sanitize_task_json(bind, "task_template_version", "definition_json")


def downgrade() -> None:
    pass
