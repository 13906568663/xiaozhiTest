from __future__ import annotations

from app.capabilities.services.model_providers import ModelProviderService


def test_normalize_config_allows_embedding_path() -> None:
    service = ModelProviderService()

    normalized = service.normalize_config(
        {
            "api_mode": "openai_compatible",
            "api_host": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_path": "/embeddings",
            "api_key": "dashscope-key",
            "model_name": "text-embedding-v4",
        }
    )

    assert normalized["api_host"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert normalized["api_path"] == "/embeddings"


def test_normalize_config_splits_full_endpoint_into_host_and_path() -> None:
    service = ModelProviderService()

    normalized = service.normalize_config(
        {
            "api_mode": "openai_compatible",
            "api_host": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
            "api_path": "/embeddings",
            "api_key": "dashscope-key",
            "model_name": "text-embedding-v4",
        }
    )

    assert normalized["api_host"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert normalized["api_path"] == "/embeddings"


def test_normalize_config_accepts_deepseek_compatible_mode() -> None:
    service = ModelProviderService()

    normalized = service.normalize_config(
        {
            "api_mode": "deepseek_compatible",
            "api_host": "https://api.deepseek.com",
            "api_path": "/chat/completions",
            "api_key": "deepseek-key",
            "model_name": "deepseek-chat",
            "memory_compression_threshold": 16000,
        }
    )

    assert normalized["api_mode"] == "deepseek_compatible"
    assert normalized["api_host"] == "https://api.deepseek.com"
    assert normalized["api_path"] == "/chat/completions"
    assert normalized["memory_compression_threshold"] == 16000


def test_normalize_config_defaults_auth_header_when_unspecified() -> None:
    service = ModelProviderService()

    normalized = service.normalize_config(
        {
            "api_mode": "openai_compatible",
            "api_host": "https://api.openai.com/v1",
            "api_path": "/chat/completions",
            "api_key": "sk-openai",
        }
    )

    # 未配置时回落到默认 Authorization: Bearer xxx，保持向后兼容。
    assert normalized["auth_header_name"] == "Authorization"
    assert normalized["auth_header_scheme"] == "Bearer "


def test_normalize_config_preserves_custom_auth_header_for_gateway() -> None:
    service = ModelProviderService()

    normalized = service.normalize_config(
        {
            "api_mode": "openai_compatible",
            "api_host": "http://gateway.example.com/v1",
            "api_path": "/chat/completions",
            "api_key": "sk-gateway-token",
            "auth_header_name": "Authorization-Gateway",
            "auth_header_scheme": "",
        }
    )

    # 网关接入：自定义头 + 空前缀（直接透传 token）。
    assert normalized["auth_header_name"] == "Authorization-Gateway"
    assert normalized["auth_header_scheme"] == ""
