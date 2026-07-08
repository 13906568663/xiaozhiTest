"""MCP 客户端的构建、调用与工具名推断（基于 app.runtime_core.mcp_client）。"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult

from app.runtime_core.mcp_client import (
    HttpStatefulMCPClient,
    HttpStatelessMCPClient,
    StdioStatefulMCPClient,
)
from app.workflow.runtime.helpers import (
    coerce_str_dict,
    snapshot_json,
)


MCPClientLike = (
    HttpStatelessMCPClient
    | HttpStatefulMCPClient
    | StdioStatefulMCPClient
)


def build_mcp_client(
    config: dict[str, Any],
    *,
    name_hint: str,
) -> MCPClientLike | None:
    """根据 capability 配置构造对应的 MCP client。"""
    if not config:
        return None

    client_type = str(
        config.get("client_type") or config.get("type") or "http_stateless",
    ).strip()
    name = str(config.get("name") or name_hint)
    timeout_seconds = float(
        config.get("timeout_seconds") or config.get("timeout") or 30
    )
    headers = coerce_str_dict(config.get("headers")) or {}
    sse_read_timeout = float(config.get("sse_read_timeout", 300))

    if client_type == "http_stateless":
        return HttpStatelessMCPClient(
            name=name,
            url=str(config.get("url") or ""),
            headers=headers,
            timeout=timeout_seconds,
            sse_read_timeout=sse_read_timeout,
        )
    if client_type == "http_stateful":
        return HttpStatefulMCPClient(
            name=name,
            url=str(config.get("url") or ""),
            headers=headers,
            timeout=timeout_seconds,
            sse_read_timeout=sse_read_timeout,
        )
    if client_type == "stdio_stateful":
        return StdioStatefulMCPClient(
            name=name,
            command=str(config.get("command") or ""),
            args=[str(item) for item in config.get("args", [])],
            env=coerce_str_dict(config.get("env")),
            cwd=str(config["cwd"]) if config.get("cwd") else None,
        )
    raise ValueError(f"Unsupported MCP client_type '{client_type}'.")


async def invoke_mcp_binding(
    config: dict[str, Any],
    *,
    binding_ref: str | None = None,
    call_kwargs: dict[str, Any],
    fallback_payload: dict[str, Any],
    name_hint: str,
) -> dict[str, Any]:
    """调用一个 MCP binding，并统一返回 ok/result/error_message 结构。"""
    client = build_mcp_client(config, name_hint=name_hint)
    if client is None:
        return {
            "ok": False,
            "error_message": "Failed to build MCP client from empty config.",
        }
    if not call_kwargs:
        call_kwargs = snapshot_json(fallback_payload)

    should_close = False
    try:
        if getattr(client, "is_stateful", False):
            await client.connect()
            should_close = True
        tool_name, tool_name_error = await resolve_mcp_tool_name(
            client, config=config, binding_ref=binding_ref
        )
        if not tool_name:
            return {
                "ok": False,
                "error_message": tool_name_error or "Failed to resolve MCP tool name.",
            }

        raw_result = await client.call_tool(tool_name, call_kwargs)
        if not isinstance(raw_result, CallToolResult):
            return {
                "ok": False,
                "error_message": (
                    f"Unexpected MCP tool result type: {type(raw_result).__name__}"
                ),
            }
        result_payload = raw_result.model_dump(mode="json", by_alias=True)
        if raw_result.isError:
            return {
                "ok": False,
                "error_message": json.dumps(
                    result_payload, ensure_ascii=False, default=str
                ),
            }
        return {"ok": True, "result": result_payload}
    except Exception as exc:
        return {"ok": False, "error_message": str(exc)}
    finally:
        if should_close:
            try:
                await client.close()
            except Exception:
                pass


async def resolve_mcp_tool_name(
    client: Any,
    *,
    config: dict[str, Any],
    binding_ref: str | None,
) -> tuple[str | None, str | None]:
    """根据配置和服务端 metadata 推断真正要调用的 MCP tool 名。"""
    legacy_tool_name = str(config.get("tool_name") or "").strip()
    if legacy_tool_name:
        return _normalize_mcp_tool_name(legacy_tool_name), None

    discovered_names: list[str] = []
    try:
        tools = await client.list_tools()
        discovered_names = [
            str(getattr(t, "name", "")).strip()
            for t in tools
            if str(getattr(t, "name", "")).strip()
        ]
    except Exception:
        discovered_names = []

    if len(discovered_names) == 1:
        return discovered_names[0], None

    binding_name = str(binding_ref or "").strip()
    if binding_name:
        binding_tool_name = _match_binding_ref_to_tool_name(
            binding_name, discovered_names
        )
        if binding_tool_name:
            return binding_tool_name, None

    if discovered_names:
        return (
            None,
            "MCP server exposes multiple tools. Please make capability code/ref match one tool name.",
        )
    return None, "Unable to resolve MCP tool name from server metadata."


def _normalize_mcp_tool_name(raw: str) -> str:
    value = str(raw).strip()
    if "." not in value:
        return value
    return value.rsplit(".", 1)[-1].strip() or value


def _match_binding_ref_to_tool_name(
    binding_ref: str,
    discovered_names: list[str],
) -> str | None:
    candidates = [str(binding_ref).strip()]
    normalized = _normalize_mcp_tool_name(binding_ref)
    if normalized and normalized not in candidates:
        candidates.append(normalized)

    for candidate in candidates:
        if candidate and (not discovered_names or candidate in discovered_names):
            return candidate
    return None


async def close_mcp_clients(clients: list[Any]) -> None:
    """按注册的逆序关闭 MCP client，降低资源泄漏风险。"""
    for client in reversed(clients):
        try:
            await client.close()
        except Exception:
            pass
