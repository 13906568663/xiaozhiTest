"""模型服务商探测与配置归一化服务。

discover_models 通过标准 /models 端点列举可用模型，使用标准库 urllib
而非 httpx/requests，避免引入额外异步依赖（探测操作是一次性同步调用）。
_extract_model_ids 兼容 OpenAI 格式（data[]）、自研格式（models[]）和纯数组格式。
"""

from __future__ import annotations

import json
import os
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.capabilities.schemas import (
    ModelProviderCheckResponse,
    ModelProviderConfig,
    ModelProviderDiscoverResponse,
    ModelProviderProbeRequest,
)
from app.core.config import get_settings
from app.domain.enums import ModelApiMode


class UnsupportedModelProviderModeError(NotImplementedError):
    """请求的 API 协议模式尚未实现，预留给将来扩展非 OpenAI 协议。"""


class ModelProviderService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def normalize_config(self, config_json: dict[str, object]) -> dict[str, object]:
        """将用户输入的配置通过 Schema 校验并归一化，排除 None 值后存入数据库。"""
        config = ModelProviderConfig.model_validate(config_json or {})
        self._validate_provider_support(config.api_mode)

        config_payload = config.model_dump(exclude_none=True)
        api_host, api_path = self._normalize_host_and_path(
            config.api_host, config.api_path
        )
        if api_host:
            config_payload["api_host"] = api_host
        config_payload["api_path"] = api_path
        return config_payload

    def check(self, payload: ModelProviderProbeRequest) -> ModelProviderCheckResponse:
        """连通性检测：发现模型并汇总结果，不抛出异常。"""
        discovered = self.discover_models(payload)
        count = len(discovered.models)
        return ModelProviderCheckResponse(
            ok=True,
            api_mode=discovered.api_mode,
            api_host=discovered.api_host,
            api_path=discovered.api_path,
            models_endpoint=discovered.models_endpoint,
            model_count=count,
            message=f"连接成功，发现 {count} 个模型。",
        )

    def discover_models(
        self, payload: ModelProviderProbeRequest
    ) -> ModelProviderDiscoverResponse:
        """调用模型服务商的 /models 接口，返回可用模型 ID 列表。

        network_compatibility=True 时添加 Connection: close 和自定义 User-Agent，
        以绕过某些代理或反向代理对持久连接的限制。
        """
        self._validate_provider_support(payload.api_mode)

        api_host, api_path = self._normalize_host_and_path(
            payload.api_host, payload.api_path
        )

        api_key = self._resolve_api_key(payload.api_key, payload.api_key_env)
        if not api_key:
            raise ValueError("请先填写 API 密钥，或配置可用的 API Key 环境变量。")

        models_endpoint = self._build_models_endpoint(api_host)
        # 与运行时保持一致的鉴权头规则：默认 'Authorization: Bearer xxx'，
        # 网关接入时可改为 'Authorization-Gateway: xxx'（scheme 设为 ''）。
        auth_header_name = (payload.auth_header_name or "Authorization").strip() or "Authorization"
        auth_header_scheme = (
            payload.auth_header_scheme if payload.auth_header_scheme is not None else "Bearer "
        )
        headers = {
            "Accept": "application/json",
            auth_header_name: f"{auth_header_scheme}{api_key}",
        }
        if payload.network_compatibility:
            headers["Connection"] = "close"
            headers["User-Agent"] = "agent-flow/0.1 (+model-provider-check)"

        request = urllib_request.Request(
            models_endpoint,
            headers=headers,
            method="GET",
        )

        try:
            with urllib_request.urlopen(request, timeout=15) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            detail = response_body.strip() or exc.reason
            raise ValueError(f"模型列表获取失败，HTTP {exc.code}: {detail}") from exc
        except urllib_error.URLError as exc:
            raise ValueError(f"模型列表获取失败：{exc.reason}") from exc

        try:
            payload_json = json.loads(raw_body or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("模型列表接口返回的不是合法 JSON。") from exc

        return ModelProviderDiscoverResponse(
            api_mode=payload.api_mode,
            api_host=api_host.rstrip("/"),
            api_path=api_path,
            models_endpoint=models_endpoint,
            models=self._extract_model_ids(payload_json),
        )

    def _build_models_endpoint(self, api_host: str) -> str:
        normalized_host = api_host.rstrip("/")
        if not normalized_host:
            raise ValueError("请先填写 API 主机。")
        return f"{normalized_host}/models"

    def _resolve_api_key(
        self, api_key: str | None, api_key_env: str | None
    ) -> str | None:
        """按优先级解析 API Key：请求中的值 > 环境变量 > 全局配置默认值。"""
        if api_key:
            return api_key
        if api_key_env:
            env_value = os.getenv(api_key_env)
            if env_value:
                return env_value
        return self.settings.openai_api_key

    def _validate_provider_support(self, api_mode: ModelApiMode) -> None:
        """校验 Provider 注册层支持的协议模式。

        Provider 注册表同时服务聊天模型和 embedding 模型，因此这里不再限制 api_path。
        真正进入聊天运行时后，仍会在对应执行器里校验 /chat/completions 约束。
        """
        if api_mode not in (
            ModelApiMode.OPENAI_COMPATIBLE,
            ModelApiMode.DEEPSEEK_COMPATIBLE,
        ):
            raise UnsupportedModelProviderModeError(
                "当前只支持 OpenAI 兼容模式和 DeepSeek 兼容模式，其它模式的架构已预留，后续再扩展。",
            )

    def _normalize_host_and_path(
        self,
        api_host: str | None,
        api_path: str,
    ) -> tuple[str, str]:
        normalized_host = (api_host or "").strip().rstrip("/")
        normalized_path = api_path.strip() or "/chat/completions"
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"

        # 兼容用户直接粘贴完整 endpoint 到 API 主机的场景。
        if normalized_host.endswith(normalized_path):
            normalized_host = normalized_host[: -len(normalized_path)].rstrip("/")

        return normalized_host, normalized_path

    def _extract_model_ids(self, payload: object) -> list[str]:
        """从不同格式的响应体中提取模型 ID 列表。

        支持三种常见格式：
        - 纯数组格式：[{"id": "gpt-4"}, ...]
        - OpenAI 格式：{"data": [{"id": "gpt-4"}, ...]}
        - 自研格式：{"models": ["gpt-4", ...]}
        """
        if isinstance(payload, list):
            return self._normalize_model_items(payload)
        if not isinstance(payload, dict):
            return []

        if isinstance(payload.get("data"), list):
            return self._normalize_model_items(payload["data"])
        if isinstance(payload.get("models"), list):
            return self._normalize_model_items(payload["models"])
        return []

    def _normalize_model_items(self, items: list[object]) -> list[str]:
        """去重并提取模型 ID，兼容字符串条目和字典条目两种格式。"""
        normalized: list[str] = []
        seen: set[str] = set()

        for item in items:
            model_id: str | None = None
            if isinstance(item, str):
                model_id = item.strip()
            elif isinstance(item, dict):
                # 按优先级尝试常见的 ID 字段名
                raw = item.get("id") or item.get("model") or item.get("name")
                if raw is not None:
                    model_id = str(raw).strip()

            if not model_id or model_id in seen:
                continue
            normalized.append(model_id)
            seen.add(model_id)

        return normalized
