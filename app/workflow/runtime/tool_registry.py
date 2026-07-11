"""向 ConversationRuntime 的 ToolRegistry 注册各类工具。

包括：
  * 节点生命周期控制工具（workflow_*）
  * 运行时信息查询工具（current_time / flow_instance_id）
  * HTTP function 工具
  * MCP 工具（共享一个 client；按 binding 注册到 registry，并返回 display 映射）
  * 知识库检索工具
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.toolset import DynamicTool
from app.runtime_core.tool_protocol import (
    ToolCategory,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    schema_from_openai_dict,
)
from app.workflow.runtime.helpers import snapshot_json
from app.workflow.runtime.http_invoker import (
    build_function_tool,
    build_function_tool_schema,
    invoke_http_function_binding,
)
from app.workflow.runtime.mcp_invoker import build_mcp_client
from app.workflow.runtime.session_serializer import display_tool_name
from app.workflow.runtime.template import extract_json_path
from app.workflow.schemas import TaskNodeDefinition

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session control tools (workflow_sleep_until / workflow_wait_callback / ...)
# ---------------------------------------------------------------------------


def register_session_control_tools(
    registry: ToolRegistry,
    node: TaskNodeDefinition,
) -> None:
    control_tools = [
        (
            "workflow_sleep_until",
            (
                "Record that this node wants to sleep until a future time. "
                "Use this before generate_response(wait_timer)."
            ),
        ),
        (
            "workflow_wait_callback",
            (
                "Record that this node wants to wait for an external callback. "
                "Use this before generate_response(wait_callback)."
            ),
        ),
        (
            "workflow_complete_node",
            (
                "Record that this node has reached a successful completion. "
                "Use this before generate_response(complete)."
            ),
        ),
        (
            "workflow_fail_node",
            (
                "Record that this node should fail and stop. "
                "Use this before generate_response(fail)."
            ),
        ),
    ]
    for tool_name, description in control_tools:
        fn = _build_session_control_fn(node, tool_name)
        schema = schema_from_openai_dict(
            build_function_tool_schema(
                tool_name=tool_name, description=description, config={},
            )
        )
        registry.register_function(
            name=tool_name,
            description=description,
            parameters=schema.parameters,
            fn=fn,
            category=ToolCategory.SESSION_CONTROL,
            is_read_only=True,
            parallel_safe=True,
        )


def _build_session_control_fn(node: TaskNodeDefinition, tool_name: str) -> Callable:
    async def session_control(**kwargs: Any) -> ToolResult:
        result = {
            "success": True,
            "control_tool": display_tool_name(tool_name, {}),
            "node_code": node.code,
            "accepted": True,
            "payload": snapshot_json(kwargs),
        }
        return ToolResult(output=result, metadata=result)

    session_control.__name__ = tool_name
    return session_control


# ---------------------------------------------------------------------------
# Runtime info tools
# ---------------------------------------------------------------------------


def register_runtime_info_tools(
    registry: ToolRegistry,
    node: TaskNodeDefinition,
    *,
    runtime_context: dict[str, Any],
) -> None:
    tool_specs: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
        (
            "workflow_get_current_time",
            "Return the current workflow runtime time in ISO-8601 UTC format.",
            lambda: {
                "current_time": datetime.now(timezone.utc).isoformat(),
                "timezone": "UTC",
            },
        ),
        (
            "workflow_get_flow_instance_id",
            "Return the current flow instance identifiers for this session turn.",
            lambda: {
                "flow_instance_id": runtime_context.get("flow_instance_id"),
                "task_run_id": runtime_context.get("task_run_id"),
                "node_run_id": runtime_context.get("node_run_id"),
                "workflow_id": runtime_context.get("workflow_id"),
            },
        ),
    ]
    for tool_name, description, result_builder in tool_specs:
        fn = _build_runtime_info_fn(node, tool_name, result_builder)
        registry.register_function(
            name=tool_name,
            description=description,
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            fn=fn,
            category=ToolCategory.META,
            is_read_only=True,
            parallel_safe=True,
        )


def _build_runtime_info_fn(
    node: TaskNodeDefinition,
    tool_name: str,
    result_builder: Callable[[], dict[str, Any]],
) -> Callable:
    async def runtime_info(**kwargs: Any) -> ToolResult:
        result = {
            "success": True,
            "tool_name": display_tool_name(tool_name, {}),
            "node_code": node.code,
            "accepted": True,
            "request_payload": snapshot_json(kwargs),
            "result": snapshot_json(result_builder()),
        }
        return ToolResult(output=result, metadata=result)

    runtime_info.__name__ = tool_name
    return runtime_info


# ---------------------------------------------------------------------------
# Python handler tools（把进程内 Python handler 暴露成 AGENT 可调工具）
# ---------------------------------------------------------------------------


def register_python_handler_tools(
    registry: ToolRegistry,
    node: TaskNodeDefinition,
    context: dict[str, Any],
    *,
    db_session: Any | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> None:
    """把 ``node.python_handler`` 暴露成 AGENT 节点可调用的粗粒度工具。

    适用「大模型决策 + Python 干重活」的节点：节点 ``executor=agent``，
    但配了 ``python_handler``。LLM 调一次本工具，工具内部跑现有 Python
    handler（并发/批量/降级/artifact 逻辑全复用），返回结构化结果；大结果
    由 ``ConversationRuntime`` 的 ``tool_output_postprocessor`` 自动转成
    artifact，LLM 只需在 ``generate_response`` 的 ``result`` 里原样引用。

    工具签名（给 LLM 看的 name/description/parameters）从
    ``python_handler_config`` 的三个保留键读取，其余键作为 handler 的
    ``handler_config`` 基线：

    * ``tool_name``：工具名，默认 ``run_<node.code>``
    * ``tool_description``：工具说明，默认取节点 description/name
    * ``tool_parameters_schema``：JSON Schema，默认空对象（无参即可调用）
    """
    handler_ref = (node.python_handler or "").strip()
    if not handler_ref:
        return

    cfg = dict(node.python_handler_config or {})
    tool_name = str(cfg.pop("tool_name", "") or f"run_{node.code}")
    tool_description = str(
        cfg.pop("tool_description", "")
        or node.description
        or node.name
        or f"执行 {handler_ref}"
    )
    params_schema = cfg.pop("tool_parameters_schema", None) or {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }

    from app.workflow.runtime.python_node_runtime import PythonNodeRuntime

    try:
        handler = PythonNodeRuntime._import_handler(handler_ref)
    except Exception as exc:  # noqa: BLE001 - 加载失败只跳过该工具，不炸节点
        logger.error(
            "[%s] register_python_handler_tools 加载 handler %r 失败：%s",
            node.code,
            handler_ref,
            exc,
        )
        return

    async def _run_handler(**kwargs: Any) -> ToolResult:
        # LLM 传入的参数并入 handler_config（覆盖默认）；无参即可跑。
        merged_cfg = {**cfg, **(snapshot_json(kwargs) if kwargs else {})}
        try:
            result = await handler(
                context,
                db_session=db_session,
                runtime_context=runtime_context or {},
                handler_config=merged_cfg,
                node=node,
            )
        except Exception as exc:  # noqa: BLE001 - 工具异常以错误结果回传 LLM
            logger.exception(
                "[%s] python handler tool %r raised", node.code, tool_name,
            )
            return ToolResult(
                output={
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                is_error=True,
            )
        if not isinstance(result, dict):
            return ToolResult(
                output={
                    "success": False,
                    "error": (
                        f"handler {handler_ref!r} 返回类型必须是 dict，"
                        f"实际为 {type(result).__name__}"
                    ),
                },
                is_error=True,
            )
        return ToolResult(output=snapshot_json(result))

    _run_handler.__name__ = tool_name
    registry.register_function(
        name=tool_name,
        description=tool_description,
        parameters=params_schema,
        fn=_run_handler,
        category=ToolCategory.BUILTIN,
        is_read_only=False,
    )


# ---------------------------------------------------------------------------
# HTTP function tools
# ---------------------------------------------------------------------------


def register_functions(
    registry: ToolRegistry,
    node: TaskNodeDefinition,
    context: dict[str, Any],
) -> None:
    """把节点绑定的 HTTP function 包装成 Agent 可直接调用的工具。"""
    for index, binding in enumerate(node.functions):
        if not binding.ref:
            continue
        tool_name = str(
            binding.config.get("tool_name")
            or binding.ref
            or f"{node.code}_function_{index + 1}",
        )
        tool_description = str(
            binding.config.get("tool_description")
            or binding.config.get("description")
            or f"Call HTTP API function '{binding.ref}' for node {node.code}.",
        )
        schema = schema_from_openai_dict(
            build_function_tool_schema(
                tool_name=tool_name, description=tool_description, config=binding.config,
            )
        )
        fn = build_function_tool(
            binding_config=binding.config,
            node=node,
            context=context,
            tool_name=tool_name,
            tool_description=tool_description,
        )
        registry.register_function(
            name=tool_name,
            description=tool_description,
            parameters=schema.parameters,
            fn=fn,
            category=ToolCategory.HTTP_FUNCTION,
        )


# ---------------------------------------------------------------------------
# MCP tools (delegate to mcp_client.call_tool, share one client per binding)
# ---------------------------------------------------------------------------


async def register_mcps(
    registry: ToolRegistry,
    node: TaskNodeDefinition,
    *,
    db_session: AsyncSession | None = None,
) -> tuple[list[Any], dict[str, str]]:
    """注册节点绑定的 MCP client。

    Args:
        registry: 工具注册表
        node: 节点定义
        db_session: 数据库会话，virtual_mcp 展开 dynamic_tool 时需要

    Returns:
        (connected_clients, mcp_tool_display_names)
    """
    mcp_tool_display_names: dict[str, str] = {}
    connected_clients: list[Any] = []

    for index, binding in enumerate(node.mcps):
        mcp_display = str(
            binding.ref or binding.config.get("name") or f"MCP_{index + 1}"
        )

        if _is_virtual_mcp_config(binding.config):
            try:
                await _register_virtual_mcp_tools(
                    registry,
                    node=node,
                    binding_config=binding.config,
                    mcp_display=mcp_display,
                    db_session=db_session,
                    name_collector=mcp_tool_display_names,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"虚拟 MCP 注册失败（节点 {node.code!r}，能力 {mcp_display!r}）："
                    f"{exc}"
                ) from exc
            continue

        client = build_mcp_client(
            binding.config, name_hint=f"{node.code}-mcp-{index + 1}"
        )
        if client is None:
            continue
        mcp_url = binding.config.get("url")

        try:
            if getattr(client, "is_stateful", False):
                await client.connect()
                connected_clients.append(client)

            tools = await client.list_tools()
            for tool in tools:
                tname = str(getattr(tool, "name", "") or "").strip()
                if not tname:
                    continue
                mcp_tool_display_names[tname] = f"{mcp_display}.{tname}"
                input_schema = getattr(tool, "inputSchema", None) or {}
                description = str(getattr(tool, "description", "") or "")
                _register_one_mcp_tool(
                    registry,
                    client=client,
                    tool_name=tname,
                    description=description,
                    input_schema=input_schema,
                )

        except Exception as exc:
            raise RuntimeError(
                f"MCP 注册失败（节点 {node.code!r}）：无法连接 {mcp_url!r}。"
                "请确认该 MCP 服务已启动、URL/端口正确，且本进程能访问该地址。"
            ) from exc

    return connected_clients, mcp_tool_display_names


def _is_virtual_mcp_config(config: dict[str, Any]) -> bool:
    """判断 binding.config 是否为虚拟 MCP（动态工具集）。"""
    if config.get("url"):
        return False
    return isinstance(config.get("mounted_tools"), list)


async def _register_virtual_mcp_tools(
    registry: ToolRegistry,
    *,
    node: TaskNodeDefinition,
    binding_config: dict[str, Any],
    mcp_display: str,
    db_session: AsyncSession | None,
    name_collector: dict[str, str],
) -> None:
    """把虚拟 MCP 的 mounted_tools 展开为 HTTP 工具。"""
    mounted = binding_config.get("mounted_tools") or []
    if not mounted:
        return
    if db_session is None:
        raise RuntimeError(
            "虚拟 MCP 需要数据库会话以加载动态工具集，但当前调用未提供 db_session。"
        )

    global_headers = binding_config.get("headers") or {}
    if not isinstance(global_headers, dict):
        global_headers = {}
    global_timeout = binding_config.get("timeout_seconds") or binding_config.get(
        "timeout"
    )

    tool_names = [
        str(item.get("name") or "").strip()
        for item in mounted
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if not tool_names:
        return

    mounted_by_name: dict[str, dict[str, Any]] = {
        str(item.get("name") or "").strip(): item
        for item in mounted
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    rows = (
        await db_session.scalars(
            sa.select(DynamicTool).where(DynamicTool.name.in_(tool_names))
        )
    ).all()
    by_name: dict[str, DynamicTool] = {row.name: row for row in rows}

    missing = [name for name in tool_names if name not in by_name]
    if missing:
        raise RuntimeError(
            "动态工具集中以下工具在数据库不存在: " + ", ".join(missing)
        )

    inactive = [
        name for name, row in by_name.items() if (row.status or "").lower() != "active"
    ]
    if inactive:
        raise RuntimeError(
            "动态工具集中以下工具未启用（status != active）: " + ", ".join(inactive)
        )

    auth_type = str(binding_config.get("auth_type") or "").strip().lower()
    auth_tool_name = str(binding_config.get("auth_tool") or "").strip()
    auth_credentials = _parse_auth_credentials(binding_config.get("auth_credentials"))
    token_field = _normalize_token_field_path(binding_config.get("token_field") or "")
    inject_header = (
        str(binding_config.get("inject_header") or "Authorization").strip()
        or "Authorization"
    )
    token_prefix = str(binding_config.get("token_prefix") or "")

    token_fetch_enabled = (
        auth_type == "token_fetch"
        and bool(auth_tool_name)
        and auth_tool_name in by_name
        and bool(auth_credentials)
        and token_field not in ("", "$")
    )
    token_cache = _VirtualMcpTokenCache() if token_fetch_enabled else None
    auth_tool_row = by_name.get(auth_tool_name) if token_fetch_enabled else None

    async def _do_auth_login() -> str:
        if auth_tool_row is None:
            raise RuntimeError("token_fetch 鉴权未正确初始化")
        merged_auth_headers = {**global_headers, **(auth_tool_row.headers or {})}
        binding_cfg: dict[str, Any] = {
            "url": auth_tool_row.url,
            "method": auth_tool_row.method or "POST",
            "headers": merged_auth_headers,
        }
        if global_timeout:
            binding_cfg["timeout_seconds"] = global_timeout
        try:
            response, _ = await invoke_http_function_binding(
                binding_cfg,
                call_kwargs=dict(auth_credentials),
                context={},
                payload=dict(auth_credentials),
                node=node,
            )
        except Exception as exc:
            raise RuntimeError(
                f"虚拟 MCP {mcp_display!r} token_fetch 调用 auth_tool "
                f"{auth_tool_name!r} 失败：{exc}"
            ) from exc
        token_value = extract_json_path(response, token_field)
        if not token_value:
            raise RuntimeError(
                f"虚拟 MCP {mcp_display!r} token_fetch 响应中未找到 token "
                f"字段 {token_field!r}（响应主体：{response!r}）"
            )
        token = str(token_value)
        logger.info(
            "Virtual MCP %r token_fetch login succeeded via %r (token_len=%d)",
            mcp_display,
            auth_tool_name,
            len(token),
        )
        return token

    for tool_name in tool_names:
        if token_fetch_enabled and tool_name == auth_tool_name:
            continue

        row = by_name[tool_name]
        merged_headers = {**global_headers, **(row.headers or {})}
        binding_cfg = {
            "url": row.url,
            "method": row.method or "POST",
            "headers": merged_headers,
            "input_schema": row.parameters_schema or {},
        }
        if global_timeout:
            binding_cfg["timeout_seconds"] = global_timeout

        mounted_entry = mounted_by_name.get(tool_name) or {}
        response_path = mounted_entry.get("response_path")
        if isinstance(response_path, str) and response_path.strip():
            binding_cfg["response_path"] = response_path.strip()
        response_pick = mounted_entry.get("response_pick")
        if isinstance(response_pick, dict) and response_pick:
            binding_cfg["response_pick"] = response_pick

        description = (
            row.description or f"Virtual MCP tool '{tool_name}' from {mcp_display}"
        )
        public_input_schema = (
            _strip_token_param_from_schema(row.parameters_schema or {})
            if token_fetch_enabled
            else (row.parameters_schema or {})
        )
        schema_cfg = dict(binding_cfg, input_schema=public_input_schema)
        schema = schema_from_openai_dict(
            build_function_tool_schema(
                tool_name=tool_name,
                description=description,
                config=schema_cfg,
            )
        )
        fn = build_function_tool(
            binding_config=binding_cfg,
            node=node,
            context={},
            tool_name=tool_name,
            tool_description=description,
        )

        invoker: Callable[[dict[str, Any]], Awaitable[ToolResult]]
        if token_fetch_enabled:
            assert token_cache is not None
            invoker = _build_token_fetch_invoker(
                fn=fn,
                tool_name=tool_name,
                token_cache=token_cache,
                fetch_token=_do_auth_login,
                inject_header=inject_header,
                token_prefix=token_prefix,
            )
        else:
            invoker = _build_virtual_http_invoker(fn)

        definition = ToolDefinition(
            name=tool_name,
            description=description,
            parameters=schema.parameters,
        )
        registry.register_mcp_tool(
            name=tool_name,
            definition=definition,
            invoker=invoker,
        )
        name_collector[tool_name] = f"{mcp_display}.{tool_name}"


def _build_virtual_http_invoker(
    fn: Callable[..., Awaitable[ToolResult]],
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, ToolResult]]:
    async def invoker(arguments: dict[str, Any]) -> ToolResult:
        return await fn(**(arguments or {}))

    return invoker


@dataclass
class _VirtualMcpTokenCache:
    """单个虚拟 MCP binding 共享的 token 缓存。"""

    token: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get(self) -> str | None:
        async with self._lock:
            return self.token

    async def set(self, token: str) -> None:
        async with self._lock:
            self.token = token

    async def clear(self) -> None:
        async with self._lock:
            self.token = None


def _normalize_token_field_path(path: str) -> str:
    """允许 ``entity.token`` 或 ``$.entity.token`` 两种写法。"""
    normalized = (path or "").strip()
    if not normalized:
        return "$"
    if normalized.startswith("$"):
        return normalized
    return f"$.{normalized}"


def _parse_auth_credentials(value: Any) -> dict[str, Any]:
    """auth_credentials 可使用对象或 JSON 字符串。"""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
        if isinstance(data, dict):
            return data
    return {}


def _strip_token_param_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """从 parameters_schema 中剔除 token 字段。"""
    result = dict(schema)
    properties = result.get("properties")
    if isinstance(properties, dict) and "token" in properties:
        result["properties"] = {
            key: value for key, value in properties.items() if key != "token"
        }
    required = result.get("required")
    if isinstance(required, list):
        result["required"] = [item for item in required if item != "token"]
    return result


_AUTH_FAILURE_KEYWORDS = (
    "token",
    "令牌",
    "鉴权",
    "未登录",
    "未授权",
    "无权",
    "认证",
    "登录失效",
    "登录过期",
    "已过期",
    "失效",
    "expired",
    "unauthor",
    "invalid",
    "forbidden",
)


def _looks_like_auth_failure(payload: Any) -> bool:
    """判断响应或错误负载是否表示 token 失效。"""
    if not isinstance(payload, dict):
        return False
    if payload.get("code") in (401, 403, "401", "403"):
        return True
    if payload.get("status_code") in (401, 403, "401", "403"):
        return True
    http_meta = payload.get("_http_meta")
    if isinstance(http_meta, dict) and http_meta.get("status_code") in (
        401,
        403,
        "401",
        "403",
    ):
        return True
    message = " ".join(
        str(payload.get(key) or "")
        for key in ("message", "msg", "error", "errorMsg", "error_message")
    ).lower()
    if "401" in message or "403" in message:
        return True
    return bool(message) and any(
        keyword.lower() in message for keyword in _AUTH_FAILURE_KEYWORDS
    )


def _build_token_fetch_invoker(
    *,
    fn: Callable[..., Awaitable[ToolResult]],
    tool_name: str,
    token_cache: _VirtualMcpTokenCache,
    fetch_token: Callable[[], Awaitable[str]],
    inject_header: str,
    token_prefix: str,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, ToolResult]]:
    """为业务工具注入 token，并在鉴权失败时刷新后重试一次。"""
    del inject_header

    async def _ensure_token(force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = await token_cache.get()
            if cached:
                return cached
        fresh = await fetch_token()
        await token_cache.set(fresh)
        return fresh

    async def invoker(arguments: dict[str, Any]) -> ToolResult:
        kwargs = dict(arguments or {})
        kwargs.pop("token", None)

        async def _call_with_token(token_value: str) -> ToolResult:
            call_kwargs = dict(kwargs, token=f"{token_prefix}{token_value}")
            return await fn(**call_kwargs)

        try:
            token = await _ensure_token()
        except Exception as exc:
            error = {
                "ok": False,
                "tool_name": tool_name,
                "error_message": (
                    f"虚拟 MCP token_fetch 登录失败，无法调用 {tool_name}：{exc}"
                ),
            }
            return ToolResult(
                output=json.dumps(error, ensure_ascii=False),
                is_error=True,
                metadata=error,
            )

        result = await _call_with_token(token)
        if _result_indicates_auth_failure(result):
            logger.info(
                "Virtual MCP token_fetch: %s reported auth failure, "
                "refreshing token and retrying once.",
                tool_name,
            )
            await token_cache.clear()
            try:
                fresh_token = await _ensure_token(force_refresh=True)
            except Exception as exc:
                logger.warning(
                    "Virtual MCP token_fetch: token refresh failed for %s: %s",
                    tool_name,
                    exc,
                )
                return result
            result = await _call_with_token(fresh_token)
        return result

    return invoker


def _result_indicates_auth_failure(result: ToolResult) -> bool:
    """从 ToolResult 检测是否需要刷新 token。"""
    if _looks_like_auth_failure(result.metadata):
        return True
    if isinstance(result.output, str) and result.output:
        try:
            body = json.loads(result.output)
        except (ValueError, json.JSONDecodeError):
            return False
        return _looks_like_auth_failure(body)
    return False


def _register_one_mcp_tool(
    registry: ToolRegistry,
    *,
    client: Any,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
) -> None:
    """Register a single MCP tool, sharing the given client for invocation."""
    parameters = {
        "type": "object",
        "properties": input_schema.get("properties", {}),
        "required": input_schema.get("required", []),
    }
    definition = ToolDefinition(
        name=tool_name,
        description=description,
        parameters=parameters,
    )

    async def invoke(arguments: dict[str, Any]) -> ToolResult:
        try:
            raw = await client.call_tool(tool_name, arguments)
        except Exception as exc:
            return ToolResult(output={"error": str(exc)}, is_error=True)

        is_error = bool(getattr(raw, "isError", False))
        text_parts: list[str] = []
        for c in getattr(raw, "content", []) or []:
            text = getattr(c, "text", None)
            if text:
                text_parts.append(str(text))
        output = "\n".join(text_parts) if text_parts else "(empty result)"

        metadata: dict[str, Any] = {}
        # Lift any images a tool captured (via client.last_call_images) so the
        # runtime can attach image blocks to the tool_results message.
        last_images = getattr(client, "last_call_images", None)
        if last_images:
            metadata["images"] = list(last_images)
            client.last_call_images = []

        return ToolResult(output=output, is_error=is_error, metadata=metadata)

    registry.register_mcp_tool(
        name=tool_name, definition=definition, invoker=invoke,
    )


# ---------------------------------------------------------------------------
# Knowledge base search tools
# ---------------------------------------------------------------------------


def register_knowledge_tools(
    registry: ToolRegistry,
    node: TaskNodeDefinition,
    *,
    db_session: Any,
) -> None:
    """为节点绑定的知识库注册检索工具（inject_mode=tool 时使用）。"""
    from app.domain.enums import KnowledgeInjectMode

    for index, binding in enumerate(node.knowledges):
        inject_mode = binding.config.get("inject_mode", KnowledgeInjectMode.TOOL)
        if inject_mode != KnowledgeInjectMode.TOOL and inject_mode != "tool":
            continue

        kb_code = binding.ref or f"kb_{index + 1}"
        tool_name = f"knowledge_search_{kb_code}"
        top_k = int(binding.config.get("top_k", 5))
        tool_description = (
            f"Search the knowledge base '{kb_code}' for relevant document chunks. "
            f"Pass a 'query' string to find relevant information. Returns top {top_k} results."
        )
        fn = _build_knowledge_search_fn(
            node=node,
            tool_name=tool_name,
            kb_code=kb_code,
            top_k=top_k,
            binding_config=binding.config,
            db_session=db_session,
        )
        registry.register_function(
            name=tool_name,
            description=tool_description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query text",
                    },
                },
                "required": ["query"],
            },
            fn=fn,
            category=ToolCategory.KNOWLEDGE,
            is_read_only=True,
        )


def _build_knowledge_search_fn(
    *,
    node: TaskNodeDefinition,
    tool_name: str,
    kb_code: str,
    top_k: int,
    binding_config: dict[str, Any],
    db_session: Any,
) -> Callable:
    async def knowledge_search(**kwargs: Any) -> ToolResult:
        from app.knowledge.services import knowledge_base as kb_svc
        from app.knowledge.services.retrieval import search_by_text

        query = kwargs.get("query", "")
        if not query:
            err = {"success": False, "tool_name": tool_name, "error": "query parameter is required"}
            return ToolResult(output=err, is_error=True, metadata=err)

        kb = await kb_svc.get_knowledge_base_by_code(db_session, kb_code)
        if kb is None:
            err = {"success": False, "tool_name": tool_name, "error": f"Knowledge base '{kb_code}' not found"}
            return ToolResult(output=err, is_error=True, metadata=err)

        score_threshold = binding_config.get("score_threshold")
        resolved_embedding_config = await kb_svc.resolve_kb_embedding_config(
            db_session, kb,
        )
        results = await search_by_text(
            db_session,
            knowledge_base_id=kb.id,
            query=query,
            embedding_model=kb.embedding_model,
            embedding_config=resolved_embedding_config,
            top_k=top_k,
            score_threshold=float(score_threshold)
            if score_threshold is not None
            else None,
        )
        result = {
            "success": True,
            "tool_name": tool_name,
            "node_code": node.code,
            "knowledge_base": kb_code,
            "query": query,
            "results": [
                {
                    "content": r.content,
                    "score": round(r.score, 4),
                    "document_title": r.document_title,
                    "chunk_index": r.chunk_index,
                }
                for r in results
            ],
            "total": len(results),
        }
        return ToolResult(output=result, metadata=result)

    knowledge_search.__name__ = tool_name
    return knowledge_search
