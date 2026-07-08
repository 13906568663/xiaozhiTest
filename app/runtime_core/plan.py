"""Lightweight PlanNotebook.

Exposes plan-management tools that an LLM can call to break down a task into
subtasks and update their state. Other components register
``plan_change_hooks`` to react when the plan mutates (e.g. push live updates
to the frontend or persist to DB).

The shape of the serialized plan stays compatible with
``app.chatbot.services.plan_utils.serialize_plan`` so callers don't need to
change.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.runtime_core.tool_protocol import (
    ToolCategory,
    ToolRegistry,
    ToolResult,
)

logger = logging.getLogger(__name__)


PlanState = str  # "todo" | "in_progress" | "done" | "abandoned"
_VALID_STATES = ("todo", "in_progress", "done", "abandoned")


@dataclass
class Subtask:
    name: str
    description: str = ""
    expected_outcome: str = ""
    outcome: str | None = None
    state: PlanState = "todo"


@dataclass
class Plan:
    id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    name: str = "执行计划"
    description: str = ""
    expected_outcome: str = ""
    outcome: str | None = None
    state: PlanState = "todo"
    subtasks: list[Subtask] = field(default_factory=list)


PlanChangeHook = Callable[["PlanNotebook", Plan | None], Awaitable[None] | None]


class PlanNotebook:
    """Hold a single in-progress plan and expose mutation tools."""

    def __init__(self, *, max_subtasks: int = 10) -> None:
        self.max_subtasks = max(1, int(max_subtasks))
        self.current_plan: Plan | None = None
        self._hooks: list[tuple[str, PlanChangeHook]] = []

    @property
    def max_tasks(self) -> int:
        # Backwards-compat alias for callers that read ``.max_tasks``.
        return self.max_subtasks

    # ------------------------------------------------------------------
    # Hook management
    # ------------------------------------------------------------------

    def register_plan_change_hook(self, name: str, fn: PlanChangeHook) -> None:
        self._hooks.append((name, fn))

    async def _fire_changed(self) -> None:
        if not self._hooks:
            return
        import asyncio

        for name, fn in self._hooks:
            try:
                ret = fn(self, self.current_plan)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:
                logger.exception("plan_change_hook %s raised", name)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tools(self, registry: ToolRegistry) -> None:
        """Add the four plan-management tools to ``registry``."""

        async def create_plan(**kwargs: Any) -> ToolResult:
            name = str(kwargs.get("name") or "").strip() or "执行计划"
            description = str(kwargs.get("description") or "")
            expected = str(kwargs.get("expected_outcome") or "")
            raw_subtasks = kwargs.get("subtasks") or []
            # 某些 LLM 在 tool_call arguments 里会把嵌套数组再 stringify 一次，
            # 传过来的就是 JSON 字符串而不是真正的 list。这里做一次兼容解码，
            # 避免对模型一句"subtasks must be a list"就把整次调用废掉。
            if isinstance(raw_subtasks, str):
                try:
                    decoded = json.loads(raw_subtasks)
                except json.JSONDecodeError as exc:
                    return ToolResult(
                        output={
                            "error": (
                                "subtasks must be a JSON array, not a string. "
                                "Failed to decode the string you passed: "
                                f"{exc.msg}. Please pass subtasks as a real "
                                "JSON array like [{\"name\": \"...\"}, ...]."
                            ),
                        },
                        is_error=True,
                    )
                if not isinstance(decoded, list):
                    return ToolResult(
                        output={
                            "error": (
                                "subtasks must be a JSON array. After decoding "
                                f"your string we got a {type(decoded).__name__}."
                            ),
                        },
                        is_error=True,
                    )
                raw_subtasks = decoded
            if not isinstance(raw_subtasks, list):
                return ToolResult(
                    output={"error": "subtasks must be a list"}, is_error=True,
                )
            if len(raw_subtasks) > self.max_subtasks:
                return ToolResult(
                    output={
                        "error": (
                            f"too many subtasks: got {len(raw_subtasks)}, "
                            f"max allowed is {self.max_subtasks}. Please "
                            "merge or split your plan so that the subtask "
                            "count is within the limit, then retry."
                        ),
                        "max_subtasks": self.max_subtasks,
                        "received": len(raw_subtasks),
                    },
                    is_error=True,
                )

            subtasks: list[Subtask] = []
            for raw in raw_subtasks:
                if not isinstance(raw, dict):
                    continue
                subtasks.append(
                    Subtask(
                        name=str(raw.get("name") or "").strip(),
                        description=str(raw.get("description") or ""),
                        expected_outcome=str(raw.get("expected_outcome") or ""),
                    )
                )
            self.current_plan = Plan(
                name=name,
                description=description,
                expected_outcome=expected,
                subtasks=subtasks,
                state="in_progress" if subtasks else "todo",
            )
            await self._fire_changed()
            return ToolResult(output={"ok": True, "plan_id": self.current_plan.id})

        async def update_subtask_state(**kwargs: Any) -> ToolResult:
            if self.current_plan is None:
                return ToolResult(
                    output={
                        "error": (
                            "no active plan: plan_create has not been called "
                            "in this conversation. If the task is simple "
                            "enough to handle in one step, skip the plan "
                            "tools entirely. Otherwise call plan_create first."
                        ),
                    },
                    is_error=True,
                )
            raw_index = kwargs.get("index")
            # 兼容字符串数字（"0"/"3"）与浮点（3.0）；拒绝 bool / None / 非数字字符串。
            if isinstance(raw_index, bool) or raw_index is None:
                return ToolResult(
                    output={
                        "error": (
                            "index is required and must be a 0-based integer "
                            f"pointing to one of the {len(self.current_plan.subtasks)} subtasks."
                        ),
                    },
                    is_error=True,
                )
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                return ToolResult(
                    output={
                        "error": (
                            f"index must be an integer, got {raw_index!r} "
                            f"(type {type(raw_index).__name__})."
                        ),
                    },
                    is_error=True,
                )
            new_state = str(kwargs.get("state") or "").strip().lower()
            if new_state not in _VALID_STATES:
                return ToolResult(
                    output={"error": f"state must be one of {_VALID_STATES}"},
                    is_error=True,
                )
            if not (0 <= index < len(self.current_plan.subtasks)):
                return ToolResult(
                    output={
                        "error": (
                            f"index {index} out of range (valid: "
                            f"0..{len(self.current_plan.subtasks) - 1})"
                        ),
                    },
                    is_error=True,
                )
            sub = self.current_plan.subtasks[index]
            sub.state = new_state
            outcome = kwargs.get("outcome")
            if outcome is not None:
                # 某些模型会把 outcome 塞成 dict/list。直接 str() 会得到 Python
                # repr（'{'foo': 'bar'}'），UI 上很难看；这里改成 JSON 序列化，
                # 字符串原样保留。
                if isinstance(outcome, str):
                    sub.outcome = outcome
                else:
                    try:
                        sub.outcome = json.dumps(outcome, ensure_ascii=False)
                    except (TypeError, ValueError):
                        sub.outcome = str(outcome)
            if all(s.state == "done" for s in self.current_plan.subtasks):
                self.current_plan.state = "done"
            elif any(s.state == "in_progress" for s in self.current_plan.subtasks):
                self.current_plan.state = "in_progress"
            await self._fire_changed()
            return ToolResult(output={"ok": True, "index": index, "state": new_state})

        async def finish_plan(**kwargs: Any) -> ToolResult:
            # 没活动 plan 时，把"想收尾"当作幂等 noop：避免 UI 上出现红色失败
            # 工具调用，也避免主 AI 把这条错误当成"还需要再补一次"的信号反复
            # 重试。常见触发场景：本轮根本没调 plan_create（简单一步任务），
            # 但模型仍按 prompt 末尾的"全部完成后调 plan_finish"想收官。
            if self.current_plan is None:
                return ToolResult(
                    output={
                        "ok": True,
                        "noop": True,
                        "reason": (
                            "no active plan; nothing to finish. If the task "
                            "does not require a plan, just produce the final "
                            "answer without calling plan_finish."
                        ),
                    },
                )
            # 兜底：收官时把仍处于 todo / in_progress 的子任务自动标记为 done。
            # 部分模型（如 DeepSeek）会把最后一步的产出直接写进最终回复正文，却漏
            # 调 plan_update_subtask(done) 就 plan_finish，导致计划卡片出现「整体
            # 已完成、但还有子任务待执行」的矛盾态。这里统一补齐，保证视图一致。
            auto_done = [
                i for i, s in enumerate(self.current_plan.subtasks)
                if s.state in ("todo", "in_progress")
            ]
            for i in auto_done:
                sub = self.current_plan.subtasks[i]
                sub.state = "done"
                if not sub.outcome:
                    sub.outcome = "（随计划收官自动完成）"
            self.current_plan.state = "done"
            outcome = kwargs.get("outcome")
            if outcome is not None:
                self.current_plan.outcome = str(outcome)
            await self._fire_changed()
            return ToolResult(output={"ok": True, "auto_completed_subtasks": auto_done})

        async def abandon_plan(**kwargs: Any) -> ToolResult:
            if self.current_plan is None:
                return ToolResult(
                    output={
                        "ok": True,
                        "noop": True,
                        "reason": (
                            "no active plan; nothing to abandon. If the task "
                            "does not require a plan, just produce the final "
                            "answer without calling plan_abandon."
                        ),
                    },
                )
            self.current_plan.state = "abandoned"
            await self._fire_changed()
            return ToolResult(output={"ok": True})

        registry.register_function(
            name="plan_create",
            description=(
                "Create a structured execution plan with up to "
                f"{self.max_subtasks} subtasks. Call this once at the start of "
                "a complex task to break it down."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "expected_outcome": {"type": "string"},
                    "subtasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "expected_outcome": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["name", "subtasks"],
            },
            fn=create_plan,
            category=ToolCategory.META,
        )
        registry.register_function(
            name="plan_update_subtask",
            description=(
                "Update one subtask's state (todo / in_progress / done / "
                "abandoned). Call this whenever you start or finish a subtask."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "state": {
                        "type": "string",
                        "enum": list(_VALID_STATES),
                    },
                    "outcome": {"type": "string"},
                },
                "required": ["index", "state"],
            },
            fn=update_subtask_state,
            category=ToolCategory.META,
        )
        registry.register_function(
            name="plan_finish",
            description="Mark the entire plan as done.",
            parameters={
                "type": "object",
                "properties": {"outcome": {"type": "string"}},
            },
            fn=finish_plan,
            category=ToolCategory.META,
        )
        registry.register_function(
            name="plan_abandon",
            description="Mark the plan as abandoned (the goal can no longer be reached).",
            parameters={"type": "object", "properties": {}},
            fn=abandon_plan,
            category=ToolCategory.META,
        )


__all__ = ["Plan", "PlanNotebook", "PlanChangeHook", "Subtask"]
