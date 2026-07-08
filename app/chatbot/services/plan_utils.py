"""Plan serialization helpers used by the chat (普通模式) PlanNotebook flow.

注意：子专家（NodeRuntime）已不再注册 PlanNotebook，因此本模块只服务于
``ChatEngine`` 在普通聊天模式下的"主 AI 实时计划"展示，不再被 workflow
节点路径调用。
"""

from __future__ import annotations

from typing import Any


def serialize_plan(plan: Any | None) -> dict[str, Any] | None:
    """Serialize a ``runtime_core`` PlanNotebook plan object to a JSON-safe dict.

    Used by both the chat SSE stream and the workflow runtime real-time
    persistence hook.
    """
    if plan is None:
        return None

    state = getattr(plan, "state", "todo")
    if state not in ("todo", "in_progress", "done", "abandoned"):
        state = "todo"

    subtasks: list[dict[str, Any]] = []
    for index, subtask in enumerate(getattr(plan, "subtasks", []) or []):
        subtask_state = getattr(subtask, "state", "todo")
        if subtask_state not in ("todo", "in_progress", "done", "abandoned"):
            subtask_state = "todo"
        outcome = getattr(subtask, "outcome", None)
        subtasks.append(
            {
                "index": index,
                "name": str(getattr(subtask, "name", "") or ""),
                "description": str(getattr(subtask, "description", "") or ""),
                "expected_outcome": str(getattr(subtask, "expected_outcome", "") or ""),
                "outcome": str(outcome) if outcome is not None else None,
                "state": subtask_state,
            }
        )

    if subtasks and all(task["state"] == "done" for task in subtasks):
        state = "done"

    outcome = getattr(plan, "outcome", None)
    return {
        "id": str(getattr(plan, "id", "") or ""),
        "name": str(getattr(plan, "name", "") or "执行计划"),
        "description": str(getattr(plan, "description", "") or ""),
        "expected_outcome": str(getattr(plan, "expected_outcome", "") or ""),
        "outcome": str(outcome) if outcome is not None else None,
        "state": state,
        "subtasks": subtasks,
    }
