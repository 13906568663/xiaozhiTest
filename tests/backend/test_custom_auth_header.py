"""Custom authentication header (e.g. Authorization-Gateway) regression tests.

Covers the gateway integration path where the upstream rejects the standard
``Authorization: Bearer xxx`` header and expects something like
``Authorization-Gateway: sk-xxx`` (no scheme prefix).
"""

from __future__ import annotations

import pytest

from app.capabilities.schemas import ModelProviderConfig
from app.chatbot.services.chat_engine import ChatEngine
from app.chatbot.services.goal_judge import GoalJudge
from app.core.config import get_settings
from app.runtime_core.provider import OpenAICompatProvider
from app.schemas.common import CapabilityBinding
from app.domain.enums import BindingSource
from app.workflow.runtime.node_runtime import NodeRuntime
from app.workflow.schemas import TaskNodeDefinition


GATEWAY_API_KEY = "sk-3ca86a7b-f334-46b8-a20d-d2e5bd10f375"


def _gateway_config() -> dict[str, object]:
    return {
        "api_mode": "openai_compatible",
        "api_host": "http://188.103.147.179:30175/gateway/api/qvTIUF/v1",
        "api_path": "/chat/completions",
        "api_key": GATEWAY_API_KEY,
        "model_name": "qwen3.5",
        "auth_header_name": "Authorization-Gateway",
        "auth_header_scheme": "",
    }


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "fallback-key")
    monkeypatch.setattr(settings, "openai_base_url", "https://env.example/v1")
    monkeypatch.setattr(settings, "default_model_name", "gpt-default")
    return settings


def test_schema_defaults_match_legacy_authorization_bearer() -> None:
    config = ModelProviderConfig.model_validate({"api_host": "https://api.openai.com/v1"})
    assert config.auth_header_name == "Authorization"
    assert config.auth_header_scheme == "Bearer "


def test_schema_accepts_custom_gateway_auth_header() -> None:
    config = ModelProviderConfig.model_validate(_gateway_config())
    assert config.auth_header_name == "Authorization-Gateway"
    assert config.auth_header_scheme == ""


def test_provider_request_uses_default_authorization_header_when_not_overridden() -> None:
    provider = OpenAICompatProvider(
        api_key="sk-openai", base_url="https://api.openai.com/v1", model="gpt-4o",
    )
    body, headers, url = provider._build_request([], tools=None, stream=False)
    assert headers["Authorization"] == "Bearer sk-openai"
    assert "Authorization-Gateway" not in headers
    assert url == "https://api.openai.com/v1/chat/completions"


def test_provider_request_uses_custom_gateway_header_with_empty_scheme() -> None:
    provider = OpenAICompatProvider(
        api_key=GATEWAY_API_KEY,
        base_url="http://188.103.147.179:30175/gateway/api/qvTIUF/v1",
        model="qwen3.5",
        auth_header_name="Authorization-Gateway",
        auth_header_scheme="",
    )
    body, headers, url = provider._build_request([], tools=None, stream=False)
    # 关键断言：完全按 curl 示例那样发出 'Authorization-Gateway: sk-xxx'，没有 'Bearer ' 前缀。
    assert headers["Authorization-Gateway"] == GATEWAY_API_KEY
    assert "Authorization" not in headers
    assert url == "http://188.103.147.179:30175/gateway/api/qvTIUF/v1/chat/completions"
    assert body["model"] == "qwen3.5"


def test_chat_engine_propagates_custom_auth_header_to_provider(
    settings_override,
) -> None:
    provider = ChatEngine()._build_provider(_gateway_config())

    assert provider is not None
    assert provider.auth_header_name == "Authorization-Gateway"
    assert provider.auth_header_scheme == ""

    _, headers, _ = provider._build_request([], tools=None, stream=False)
    assert headers["Authorization-Gateway"] == GATEWAY_API_KEY


def test_goal_judge_propagates_custom_auth_header_to_provider(
    settings_override,
) -> None:
    provider = GoalJudge()._build_provider(_gateway_config())

    assert provider is not None
    assert provider.auth_header_name == "Authorization-Gateway"
    assert provider.auth_header_scheme == ""


def test_node_runtime_propagates_custom_auth_header_to_provider(
    settings_override,
) -> None:
    runtime = NodeRuntime()
    node = TaskNodeDefinition(
        seq=1,
        code="gateway-node",
        name="Gateway Node",
        model=CapabilityBinding(
            source=BindingSource.NODE,
            config=_gateway_config(),
        ),
    )

    provider = runtime._build_provider(node)

    assert provider is not None
    assert provider.auth_header_name == "Authorization-Gateway"
    assert provider.auth_header_scheme == ""
