"""Tool abstraction (Toolkit / ToolResult).

A *handler* knows how to execute one tool. Handlers are registered into a
``ToolRegistry``. The runtime queries the registry for definitions (passed
to the LLM as ``tools=``) and dispatches tool_calls via ``registry.execute``.

设计要点：
  * Handler 同步/异步皆可，registry 统一 ``await``。
  * 统一 ``ToolResult`` (输出 + meta) 作为工具返回值。
  * 可携带 ``ToolMeta``：read_only / category 标记，便于将来做并行批处理或 Plan Mode 拦截。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition (OpenAI function-calling schema)
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """OpenAI ``tools=[...]`` 元素的精简表示。"""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_openai_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def schema_from_openai_dict(schema: Mapping[str, Any]) -> ToolDefinition:
    """Inverse of :func:`to_openai_dict` — accepts the legacy schema dicts
    used by ``app.workflow.runtime.helpers.build_function_tool_schema``."""

    if "function" in schema:
        fn = schema["function"]
        return ToolDefinition(
            name=str(fn.get("name") or ""),
            description=str(fn.get("description") or ""),
            parameters=dict(fn.get("parameters") or {"type": "object", "properties": {}}),
        )
    return ToolDefinition(
        name=str(schema.get("name") or ""),
        description=str(schema.get("description") or ""),
        parameters=dict(schema.get("parameters") or {"type": "object", "properties": {}}),
    )


# ---------------------------------------------------------------------------
# Tool category / metadata
# ---------------------------------------------------------------------------


class ToolCategory(str, Enum):
    META = "meta"
    SESSION_CONTROL = "session_control"
    HTTP_FUNCTION = "http_function"
    MCP = "mcp"
    KNOWLEDGE = "knowledge"
    BUILTIN = "builtin"
    DISPATCH = "dispatch"


@dataclass
class ToolMeta:
    name: str
    category: ToolCategory = ToolCategory.META
    is_read_only: bool = False
    # 是否允许与同批次的其它 parallel_safe 工具并发执行。
    # 默认 False：很多"只读"工具（知识库检索 / load_skill / wiki）闭包里共享
    # 同一个 AsyncSession，SQLAlchemy 不允许并发操作同一会话——因此并行安全
    # 必须由注册方显式声明，仅纯内存 / 每次调用独立资源的工具才应标 True。
    parallel_safe: bool = False
    description: str = ""


# ---------------------------------------------------------------------------
# Tool execution context
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Per-call context handed to tool handlers."""

    workspace_root: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    db_session: Any = None
    runtime_context: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool result
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Result returned by a ``ToolHandler.execute``.

    ``output`` 可以是任意可 JSON 序列化对象（dict/list/str/...）。Runtime 在写
    入消息时会调用 :meth:`output_text` 拿到适合塞进 ``tool_result`` block 的字
    符串；额外的 ``metadata`` 用于驱动控制流（例如 ``set_session_action``、
    ``decision`` 等）。
    """

    output: Any = None
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def output_text(self) -> str:
        if isinstance(self.output, str):
            return self.output
        if self.output is None:
            return ""
        try:
            return json.dumps(self.output, ensure_ascii=False, default=str)
        except Exception:
            return str(self.output)


# ---------------------------------------------------------------------------
# Handler protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolHandler(Protocol):
    meta: ToolMeta
    definition: ToolDefinition

    async def execute(  # pragma: no cover - protocol
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult: ...


HandlerFn = Callable[..., Any]


@dataclass
class FunctionToolHandler:
    """Wrap a plain function/coroutine into a ``ToolHandler``.

    ``fn`` 签名兼容以下任意一种：
      * ``async def fn(**kwargs) -> Any``
      * ``async def fn(args: dict, context: ToolContext) -> Any``
      * ``def fn(**kwargs) -> Any``
      * ``def fn(args: dict, context: ToolContext) -> Any``

    ``Any`` 返回值如果不是 :class:`ToolResult`，会被自动包成
    ``ToolResult(output=value)``。
    """

    meta: ToolMeta
    definition: ToolDefinition
    fn: HandlerFn
    needs_context: bool = False

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            if self.needs_context:
                raw = self.fn(arguments, context)
            else:
                raw = self.fn(**(arguments or {}))
            if inspect.isawaitable(raw):
                raw = await raw  # type: ignore[assignment]
        except TypeError as exc:
            return ToolResult(
                output={"error": f"Bad arguments for tool {self.meta.name!r}: {exc}"},
                is_error=True,
            )
        except Exception as exc:
            logger.exception("Tool %s raised", self.meta.name)
            return ToolResult(output={"error": str(exc)}, is_error=True)

        if isinstance(raw, ToolResult):
            return raw
        return ToolResult(output=raw)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """A handler dictionary; the runtime queries definitions/execute through it."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        # MCP tools have their own dispatch path because they share one client.
        self._mcp_definitions: dict[str, ToolDefinition] = {}
        self._mcp_invokers: dict[str, Callable[[dict[str, Any]], Awaitable[ToolResult]]] = {}

    # -------------------- Registration --------------------

    def register_handler(self, handler: ToolHandler) -> None:
        self._handlers[handler.meta.name] = handler

    def register_function(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any] | None,
        fn: HandlerFn,
        category: ToolCategory = ToolCategory.META,
        is_read_only: bool = False,
        parallel_safe: bool = False,
        needs_context: bool = False,
    ) -> None:
        meta = ToolMeta(
            name=name,
            category=category,
            is_read_only=is_read_only,
            parallel_safe=parallel_safe,
            description=description,
        )
        definition = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
        )
        self.register_handler(
            FunctionToolHandler(
                meta=meta, definition=definition, fn=fn, needs_context=needs_context,
            )
        )

    def register_mcp_tool(
        self,
        *,
        name: str,
        definition: ToolDefinition,
        invoker: Callable[[dict[str, Any]], Awaitable[ToolResult]],
    ) -> None:
        self._mcp_definitions[name] = definition
        self._mcp_invokers[name] = invoker

    def remove(self, name: str) -> None:
        self._handlers.pop(name, None)
        self._mcp_definitions.pop(name, None)
        self._mcp_invokers.pop(name, None)

    # -------------------- Inspection --------------------

    def has(self, name: str) -> bool:
        return name in self._handlers or name in self._mcp_definitions

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._mcp_definitions

    def get_handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    def names(self) -> list[str]:
        return sorted(set(self._handlers) | set(self._mcp_definitions))

    def is_read_only(self, name: str) -> bool:
        h = self._handlers.get(name)
        return bool(h and h.meta.is_read_only)

    def is_parallel_safe(self, name: str) -> bool:
        """工具是否声明了可与同批次工具并发执行（MCP 工具一律视为不可）。"""
        h = self._handlers.get(name)
        return bool(h and h.meta.parallel_safe)

    # -------------------- For LLM API --------------------

    def openai_definitions(self) -> list[dict[str, Any]]:
        defs: list[dict[str, Any]] = []
        for handler in self._handlers.values():
            defs.append(handler.definition.to_openai_dict())
        for name in sorted(self._mcp_definitions):
            defs.append(self._mcp_definitions[name].to_openai_dict())
        return defs

    # -------------------- Execution --------------------

    async def execute(
        self, name: str, arguments: dict[str, Any], context: ToolContext,
    ) -> ToolResult:
        if name in self._mcp_invokers:
            try:
                return await self._mcp_invokers[name](arguments or {})
            except Exception as exc:
                logger.exception("MCP tool %s failed", name)
                return ToolResult(output={"error": str(exc)}, is_error=True)

        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(output={"error": f"Unknown tool: {name!r}"}, is_error=True)
        return await handler.execute(arguments or {}, context)


__all__ = [
    "FunctionToolHandler",
    "HandlerFn",
    "ToolCategory",
    "ToolContext",
    "ToolDefinition",
    "ToolHandler",
    "ToolMeta",
    "ToolRegistry",
    "ToolResult",
    "schema_from_openai_dict",
]
