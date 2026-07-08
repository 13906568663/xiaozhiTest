"""HTTP function 绑定的调用与 schema 构建。

负责将节点绑定的 HTTP API 配置转换为可注册到 ``app.runtime_core.ToolRegistry``
的工具函数，以及执行实际的 HTTP 请求（含模板解析、query 拼接、响应裁剪）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from app.runtime_core.tool_protocol import ToolResult
from app.workflow.runtime.helpers import (
    coerce_http_method,
    coerce_str_dict,
    snapshot_json,
)
from app.workflow.runtime.template import (
    apply_response_pick,
    extract_json_path,
    resolve_value_template,
)
from app.workflow.schemas import TaskNodeDefinition

# 元信息 key：调用方从 ``ToolResult.metadata[HTTP_META_KEY]`` 拿到 status_code /
# method / duration_ms，用于工具调用日志埋点。失败路径（抛 RuntimeError）的
# 元信息通过异常的 ``http_meta`` 属性传出，由 build_function_tool 兜底回收。
HTTP_META_KEY = "_http_meta"


class HttpInvokeError(RuntimeError):
    """HTTP function 调用失败时抛出的异常。

    携带 ``http_meta``（``status_code`` / ``method`` / ``duration_ms`` 等），
    便于上层 wrapper 把这些信息塞进 ``ToolResult.metadata`` 供埋点使用。
    """

    def __init__(self, message: str, *, http_meta: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.http_meta = http_meta or {}

FUNCTION_META_KEYS = frozenset(
    {
        "tool_name",
        "tool_description",
        "tool_json_schema",
        "json_schema",
        "input_schema",
        "output_schema",
        "url",
        "method",
        "headers",
        "timeout_seconds",
        "query_params",
        "body_template",
        "response_path",
        "response_pick",
        "call_args",
        "description",
    }
)


def build_function_tool(
    *,
    binding_config: dict[str, Any],
    node: TaskNodeDefinition,
    context: dict[str, Any],
    tool_name: str,
    tool_description: str,
) -> Any:
    """把 HTTP function 配置包成可注册到 ToolRegistry 的异步函数。"""

    async def runtime_function_tool(**kwargs: Any) -> ToolResult:
        http_meta: dict[str, Any] = {}
        try:
            result, http_meta = await invoke_http_function_binding(
                binding_config,
                call_kwargs=kwargs,
                context=context,
                payload=kwargs,
                node=node,
            )
        except HttpInvokeError as exc:
            result = {"ok": False, "error_message": str(exc)}
            http_meta = dict(exc.http_meta)
        except Exception as exc:
            result = {"ok": False, "error_message": str(exc)}
        is_error = bool(result.get("ok") is False or result.get("error_message"))
        metadata: dict[str, Any] = (
            dict(result) if isinstance(result, dict) else {"result": result}
        )
        if http_meta:
            metadata[HTTP_META_KEY] = http_meta
        return ToolResult(
            output=json.dumps(snapshot_json(result), ensure_ascii=False, default=str),
            is_error=is_error,
            metadata=metadata,
        )

    runtime_function_tool.__name__ = tool_name
    runtime_function_tool.__doc__ = tool_description
    return runtime_function_tool


def build_function_tool_schema(
    *,
    tool_name: str,
    description: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """为 function tool 生成 OpenAI function calling 所需的 JSON schema。"""
    custom_schema = config.get("tool_json_schema") or config.get("json_schema")
    if isinstance(custom_schema, dict):
        return custom_schema

    input_schema = config.get("input_schema")
    if isinstance(input_schema, dict):
        parameters = input_schema
        if (
            parameters.get("type") != "object"
            and "properties" not in parameters
            and "additionalProperties" not in parameters
        ):
            parameters = {
                "type": "object",
                "properties": parameters,
                "additionalProperties": True,
            }
        elif parameters.get("type") != "object":
            parameters = {
                "type": "object",
                "additionalProperties": True,
                **parameters,
            }
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": description,
                "parameters": parameters,
            },
        }

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            },
        },
    }


def extract_function_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """从配置里抽出默认入参，兼容若干历史字段名。"""
    if "call_args" in config and isinstance(config["call_args"], dict):
        return dict(config["call_args"])
    if "preset_kwargs" in config and isinstance(config["preset_kwargs"], dict):
        return dict(config["preset_kwargs"])
    if "preset_args" in config and isinstance(config["preset_args"], dict):
        return dict(config["preset_args"])
    return {
        key: value for key, value in config.items() if key not in FUNCTION_META_KEYS
    }


async def invoke_http_function_binding(
    config: dict[str, Any],
    *,
    call_kwargs: dict[str, Any],
    context: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    node: TaskNodeDefinition | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """执行 HTTP function 绑定，并在必要时做模板解析与响应裁剪。

    返回 ``(response_body, http_meta)``：
      - ``response_body``：经过 response_path / response_pick 处理后的响应体；
        非 dict 时会包成 ``{"result": value}`` 以保持外层签名稳定。
      - ``http_meta``：``{"method", "status_code", "duration_ms", "url"}``，
        供上层 wrapper 写入 ``ToolResult.metadata`` 供埋点使用。
    """
    url = str(config.get("url") or "").strip()
    if not url:
        raise ValueError(
            "Function config requires 'url'. Legacy local-function entrypoints are no longer supported.",
        )

    method = coerce_http_method(config.get("method"))
    resolved_headers = resolve_value_template(
        dict(config.get("headers") or {}),
        context=context,
        payload=payload,
        node=node,
    )
    headers = coerce_str_dict(resolved_headers) or {}

    resolved_query = resolve_value_template(
        dict(config.get("query_params") or {}),
        context=context,
        payload=payload,
        node=node,
    )
    query_params = resolved_query if isinstance(resolved_query, dict) else {}

    body_template = config.get("body_template")
    body_payload: Any = None
    if body_template is not None:
        body_payload = resolve_value_template(
            body_template, context=context, payload=call_kwargs, node=node
        )
    elif method in {"POST", "PUT", "PATCH"}:
        body_payload = call_kwargs
    elif method == "DELETE" and call_kwargs:
        body_payload = call_kwargs

    if method == "GET" and not query_params and call_kwargs:
        query_params = snapshot_json(call_kwargs)

    timeout_seconds = float(
        config.get("timeout_seconds") or config.get("timeout") or 60,
    )

    response, http_meta = await asyncio.to_thread(
        _perform_http_request,
        method=method,
        url=url,
        headers=headers,
        query_params=query_params,
        body_payload=body_payload,
        timeout_seconds=timeout_seconds,
    )
    response_path = str(config.get("response_path") or "").strip()
    if response_path:
        extracted = extract_json_path(response, response_path)
        if extracted is None:
            raise ValueError(
                f"Function response_path '{response_path}' did not match the HTTP response payload.",
            )
        response = extracted

    response_pick = config.get("response_pick")
    if isinstance(response_pick, dict) and response_pick:
        response = apply_response_pick(response, response_pick)

    if isinstance(response, dict):
        return response, http_meta
    return {"result": response}, http_meta


def _perform_http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    query_params: dict[str, Any],
    body_payload: Any,
    timeout_seconds: float,
) -> tuple[Any, dict[str, Any]]:
    """在同步线程中发起真实 HTTP 请求，避免阻塞事件循环。

    返回 ``(parsed_body, http_meta)``，``http_meta`` 包含本次请求的元信息
    （method / status_code / duration_ms / url），用于上层埋点。
    """
    final_url = _append_query_params(url, query_params)
    request_headers = dict(headers)
    data: bytes | None = None

    if body_payload is not None:
        serializable_body = snapshot_json(body_payload)
        data = json.dumps(serializable_body, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
        request_headers.setdefault("Content-Type", "application/json")

    req = urllib_request.Request(
        final_url, data=data, headers=request_headers, method=method
    )
    start_perf = time.perf_counter()
    status_code: int | None = None
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_body = resp.read()
            response_headers = dict(resp.headers.items())
            status_code = resp.getcode()
    except urllib_error.HTTPError as exc:
        raw_body = exc.read()
        status_code = exc.code
        detail = _parse_http_response_body(
            raw_body,
            content_type=exc.headers.get("Content-Type") if exc.headers else None,
        )
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        raise HttpInvokeError(
            f"Function HTTP request failed with status {status_code}: "
            f"{json.dumps(detail, ensure_ascii=False, default=str)}",
            http_meta={
                "method": method,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "url": final_url,
            },
        ) from exc
    except urllib_error.URLError as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        raise HttpInvokeError(
            f"Function HTTP request failed: {exc.reason}",
            http_meta={
                "method": method,
                "status_code": None,
                "duration_ms": duration_ms,
                "url": final_url,
            },
        ) from exc

    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    http_meta: dict[str, Any] = {
        "method": method,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "url": final_url,
    }

    parsed_body = _parse_http_response_body(
        raw_body, content_type=response_headers.get("Content-Type")
    )
    if parsed_body is None:
        return {"status_code": status_code, "ok": True}, http_meta
    return parsed_body, http_meta


def _parse_http_response_body(
    raw_body: bytes,
    *,
    content_type: str | None,
) -> Any:
    """尽量把响应体解析成 JSON，失败时退化成 text 包装。"""
    if not raw_body:
        return None

    text = raw_body.decode("utf-8")
    if content_type and "json" in content_type.lower():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return {"text": text}


def _append_query_params(url: str, params: dict[str, Any]) -> str:
    """把 query 参数追加到 URL，复杂对象会先转成 JSON 字符串。"""
    if not params:
        return url

    split_url = urllib_parse.urlsplit(url)
    existing_query = urllib_parse.parse_qsl(split_url.query, keep_blank_values=True)
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            rendered_value = json.dumps(value, ensure_ascii=False, default=str)
        else:
            rendered_value = str(value)
        existing_query.append((str(key), rendered_value))

    return urllib_parse.urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urllib_parse.urlencode(existing_query, doseq=True),
            split_url.fragment,
        )
    )
