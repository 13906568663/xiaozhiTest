"""虚拟 MCP token_fetch 自动鉴权单元测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.runtime_core.tool_protocol import ToolResult
from app.workflow.runtime import tool_registry as tr


@pytest.mark.parametrize(
    "given,expected",
    [
        ("entity.token", "$.entity.token"),
        ("$.entity.token", "$.entity.token"),
        ("$", "$"),
        ("", "$"),
        ("  data.access_token  ", "$.data.access_token"),
    ],
)
def test_normalize_token_field_path_accepts_both_forms(
    given: str, expected: str
) -> None:
    assert tr._normalize_token_field_path(given) == expected


def test_parse_auth_credentials_supports_dict_and_json_string() -> None:
    assert tr._parse_auth_credentials({"a": 1}) == {"a": 1}
    assert tr._parse_auth_credentials('{"account":"u","passWord":"p"}') == {
        "account": "u",
        "passWord": "p",
    }


@pytest.mark.parametrize("bad", [None, "", "not-json", 123, '"text"', "[1,2]"])
def test_parse_auth_credentials_rejects_invalid_payloads(bad: Any) -> None:
    assert tr._parse_auth_credentials(bad) == {}


def test_strip_token_param_removes_property_and_required_entry() -> None:
    schema = {
        "type": "object",
        "properties": {
            "token": {"type": "string"},
            "reportName": {"type": "string"},
            "endTime": {"type": "string"},
        },
        "required": ["token", "reportName", "endTime"],
    }
    stripped = tr._strip_token_param_from_schema(schema)
    assert "token" not in stripped["properties"]
    assert "reportName" in stripped["properties"]
    assert stripped["required"] == ["reportName", "endTime"]
    assert "token" in schema["properties"]


def test_strip_token_param_handles_missing_required_list() -> None:
    stripped = tr._strip_token_param_from_schema(
        {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
                "other": {"type": "string"},
            },
        }
    )
    assert "token" not in stripped["properties"]
    assert "required" not in stripped


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"code": 401, "message": "令牌已过期或验证不正确！"}, True),
        ({"code": "401"}, True),
        ({"status_code": 403}, True),
        ({"_http_meta": {"status_code": 401}}, True),
        ({"error_message": "Function HTTP request failed with status 401"}, True),
        ({"code": 200, "message": "ok"}, False),
        ({"message": "Token invalid or expired"}, True),
        ({"message": "Unauthorized request"}, True),
        ({"errorMsg": "鉴权失败"}, True),
        ({"message": "服务繁忙，请稍后重试"}, False),
        ("not-a-dict", False),
        (None, False),
    ],
)
def test_looks_like_auth_failure_covers_common_patterns(
    payload: Any, expected: bool
) -> None:
    assert tr._looks_like_auth_failure(payload) is expected


def test_token_cache_get_set_clear_roundtrip() -> None:
    async def scenario() -> None:
        cache = tr._VirtualMcpTokenCache()
        assert await cache.get() is None
        await cache.set("abc")
        assert await cache.get() == "abc"
        await cache.clear()
        assert await cache.get() is None

    asyncio.run(scenario())


def _ok_tool_result(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False),
        is_error=False,
        metadata=payload,
    )


def _auth_failed_tool_result() -> ToolResult:
    body = {"code": 401, "message": "令牌已过期或验证不正确！"}
    return ToolResult(
        output=json.dumps(body, ensure_ascii=False),
        is_error=False,
        metadata=body,
    )


def test_invoker_fetches_token_on_first_call_and_injects_into_kwargs() -> None:
    captured: dict[str, Any] = {}

    async def fn(**kwargs: Any) -> ToolResult:
        captured.update(kwargs)
        return _ok_tool_result({"taskId": "T-1", "status": "PENDING"})

    fetch_calls: list[int] = []

    async def fetch_token() -> str:
        fetch_calls.append(1)
        return "JWT-FRESH"

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="report_create",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="",
    )
    result = asyncio.run(
        invoker({"reportName": "高负荷报表", "endTime": "2026-05-14 00:00:00"})
    )

    assert result.is_error is False
    assert len(fetch_calls) == 1
    assert captured["token"] == "JWT-FRESH"
    assert captured["reportName"] == "高负荷报表"


def test_invoker_reuses_cached_token_on_subsequent_calls() -> None:
    fetch_calls: list[int] = []

    async def fetch_token() -> str:
        fetch_calls.append(1)
        return f"JWT-{len(fetch_calls)}"

    async def fn(**kwargs: Any) -> ToolResult:
        return _ok_tool_result({"echo": kwargs.get("token")})

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="t1",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="",
    )

    async def scenario() -> tuple[ToolResult, ToolResult]:
        return await invoker({}), await invoker({})

    first, second = asyncio.run(scenario())
    assert json.loads(first.output)["echo"] == "JWT-1"
    assert json.loads(second.output)["echo"] == "JWT-1"
    assert len(fetch_calls) == 1


def test_invoker_drops_llm_supplied_token_to_prevent_corruption() -> None:
    async def fn(**kwargs: Any) -> ToolResult:
        return _ok_tool_result({"token_seen": kwargs.get("token")})

    async def fetch_token() -> str:
        return "JWT-AUTHORITATIVE"

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="t1",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="",
    )
    result = asyncio.run(invoker({"token": "CORRUPTED-BY-LLM", "x": 1}))
    assert json.loads(result.output)["token_seen"] == "JWT-AUTHORITATIVE"


def test_invoker_refreshes_token_once_on_auth_failure_and_retries() -> None:
    call_log: list[dict[str, Any]] = []

    async def fn(**kwargs: Any) -> ToolResult:
        call_log.append(dict(kwargs))
        if len(call_log) == 1:
            return _auth_failed_tool_result()
        return _ok_tool_result({"taskId": "T-OK"})

    fetch_tokens = iter(["JWT-OLD", "JWT-NEW"])
    fetch_calls: list[str] = []

    async def fetch_token() -> str:
        token = next(fetch_tokens)
        fetch_calls.append(token)
        return token

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="t1",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="",
    )
    result = asyncio.run(invoker({"endTime": "2026-05-14 00:00:00"}))

    assert len(call_log) == 2
    assert call_log[0]["token"] == "JWT-OLD"
    assert call_log[1]["token"] == "JWT-NEW"
    assert fetch_calls == ["JWT-OLD", "JWT-NEW"]
    assert json.loads(result.output)["taskId"] == "T-OK"


def test_invoker_refreshes_on_http_401_metadata() -> None:
    call_count = 0

    async def fn(**kwargs: Any) -> ToolResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ToolResult(
                output="unauthorized",
                is_error=True,
                metadata={"_http_meta": {"status_code": 401}},
            )
        return _ok_tool_result({"token": kwargs["token"]})

    tokens = iter(["OLD", "NEW"])

    async def fetch_token() -> str:
        return next(tokens)

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="t1",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="Bearer ",
    )
    result = asyncio.run(invoker({}))
    assert call_count == 2
    assert json.loads(result.output)["token"] == "Bearer NEW"


def test_invoker_returns_login_failure_without_calling_business_tool() -> None:
    async def fn(**kwargs: Any) -> ToolResult:
        raise AssertionError("business tool should not run")

    async def fetch_token() -> str:
        raise RuntimeError("auth tool unreachable")

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="report_create",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="",
    )
    result = asyncio.run(invoker({"reportName": "x"}))
    assert result.is_error is True
    assert "auth tool unreachable" in json.loads(result.output)["error_message"]


def test_invoker_keeps_first_failure_if_refresh_token_fails() -> None:
    fetch_call_count = 0

    async def fetch_token() -> str:
        nonlocal fetch_call_count
        fetch_call_count += 1
        if fetch_call_count == 1:
            return "JWT-V1"
        raise RuntimeError("auth refresh failed")

    async def fn(**kwargs: Any) -> ToolResult:
        return _auth_failed_tool_result()

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="t1",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="",
    )
    result = asyncio.run(invoker({}))
    assert fetch_call_count == 2
    assert json.loads(result.output) == {
        "code": 401,
        "message": "令牌已过期或验证不正确！",
    }


def test_invoker_applies_token_prefix_when_configured() -> None:
    captured: dict[str, Any] = {}

    async def fn(**kwargs: Any) -> ToolResult:
        captured.update(kwargs)
        return _ok_tool_result({})

    async def fetch_token() -> str:
        return "RAW"

    invoker = tr._build_token_fetch_invoker(
        fn=fn,
        tool_name="t1",
        token_cache=tr._VirtualMcpTokenCache(),
        fetch_token=fetch_token,
        inject_header="Authorization",
        token_prefix="Bearer ",
    )
    asyncio.run(invoker({}))
    assert captured["token"] == "Bearer RAW"
