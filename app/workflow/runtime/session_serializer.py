"""会话轨迹序列化。

把 ConversationRuntime memory 展平成前端可展示的统一格式消息列表。
"""

from __future__ import annotations

from typing import Any

from app.runtime_core.messages import Msg
from app.runtime_core.runtime import DEFAULT_FINISH_TOOL_NAME
from app.workflow.runtime.helpers import snapshot_json
from app.workflow.runtime.prompt import build_session_instruction_content
from app.workflow.schemas import TaskNodeDefinition

SESSION_CONTROL_TOOL_ALIASES: dict[str, str] = {
    "workflow_sleep_until": "FlowSleep_MCP.sleep_until",
    "workflow_wait_callback": "FlowCallback_MCP.wait_callback",
    "workflow_complete_node": "FlowLifecycle_MCP.complete_node",
    "workflow_fail_node": "FlowLifecycle_MCP.fail_node",
    "workflow_get_current_time": "FlowRuntime_MCP.get_current_time",
    "workflow_get_flow_instance_id": "FlowRuntime_MCP.get_flow_instance_id",
}


def display_tool_name(
    tool_name: Any,
    mcp_tool_display_names: dict[str, str],
) -> str:
    """把内部工具名映射成更符合业务语义的展示名称。"""
    raw_name = str(tool_name or "")
    alias = SESSION_CONTROL_TOOL_ALIASES.get(raw_name)
    if alias:
        return alias
    return mcp_tool_display_names.get(raw_name, raw_name)


def serialize_session_messages(
    *,
    node: TaskNodeDefinition,
    memory_state: dict[str, Any],
    final_result: dict[str, Any] | None = None,
    mcp_tool_display_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """把 runtime memory 展平成前端可展示的会话轨迹。

    ``memory_state`` 的形状与 ``app.runtime_core.memory.Memory.state_dict()``
    保持一致：``{"content": [[msg_dict, marks], ...]}``。
    """
    display_names = mcp_tool_display_names or {}
    entries: list[dict[str, Any]] = [
        {
            "role": "system",
            "type": "instruction",
            "content": build_session_instruction_content(node),
        }
    ]
    for item in memory_state.get("content", []):
        msg_dict, _marks = _split_entry(item)
        if msg_dict is None:
            continue
        entries.extend(
            _expand_session_entries_from_msg(
                Msg.from_dict(msg_dict),
                display_names,
            )
        )

    if final_result is not None:
        entries.append(
            {
                "role": "assistant",
                "type": "final",
                "content": snapshot_json(final_result),
            }
        )

    for index, entry in enumerate(entries, start=1):
        entry["seq"] = index
    return entries


def _split_entry(item: Any) -> tuple[dict[str, Any] | None, list[Any]]:
    """Accept ``[msg_dict, marks]`` or just ``msg_dict``."""
    if isinstance(item, (list, tuple)) and len(item) == 2:
        msg_dict, raw_marks = item
        marks = list(raw_marks) if isinstance(raw_marks, (list, tuple, set)) else []
        return (msg_dict if isinstance(msg_dict, dict) else None, marks)
    if isinstance(item, dict):
        return (item, [])
    return (None, [])


def _expand_session_entries_from_msg(
    msg: Msg,
    mcp_tool_display_names: dict[str, str],
) -> list[dict[str, Any]]:
    """把单条 Msg 展开为若干条统一格式的轨迹记录。"""
    metadata = msg.metadata or {}
    if metadata.get("session_entry_type") == "resume_event":
        return [
            {
                "role": "tool",
                "type": "resume_event",
                "tool_name": metadata.get("tool_name") or "workflow_runtime",
                "content": snapshot_json(metadata.get("event") or {}),
            }
        ]

    role_value = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
    entries: list[dict[str, Any]] = []
    if role_value == "user":
        entries.append(
            {
                "role": "user",
                "type": "input",
                "content": msg.get_text_content() or snapshot_json(msg.content),
            }
        )
        return entries

    if role_value == "assistant":
        text_content = msg.get_text_content()
        if text_content:
            entries.append(
                {
                    "role": "assistant",
                    "type": "thought",
                    "content": text_content,
                }
            )
        for block in msg.get_content_blocks("tool_use"):
            if block.get("name") == DEFAULT_FINISH_TOOL_NAME:
                continue
            tool_name = display_tool_name(
                block.get("name"), mcp_tool_display_names,
            )
            entries.append(
                {
                    "role": "assistant",
                    "type": "action",
                    "tool_name": tool_name,
                    "arguments": snapshot_json(
                        block.get("input")
                        or {
                            key: value
                            for key, value in block.items()
                            if key not in {"id", "type", "name"}
                        }
                    ),
                }
            )
        return entries

    if role_value == "system":
        for block in msg.get_content_blocks("tool_result"):
            if block.get("name") == DEFAULT_FINISH_TOOL_NAME:
                continue
            tool_name = display_tool_name(
                block.get("name"), mcp_tool_display_names,
            )
            entries.append(
                {
                    "role": "tool",
                    "type": "observation",
                    "tool_name": tool_name,
                    "content": snapshot_json(block.get("output")),
                }
            )
    return entries
