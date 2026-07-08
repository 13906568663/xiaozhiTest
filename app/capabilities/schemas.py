"""Capabilities 域 Pydantic Schema — 合并 capabilities / model_providers 两类 schema。

ModelProviderConfig 以 extra="allow" 模式设计，支持存储扩展字段，
便于在不修改 Schema 的情况下向 config_json 添加新的模型参数。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import CapabilityType, ModelApiMode
from app.schemas.common import TimestampsMixin


# ---------------------------------------------------------------------------
# Capability schemas
# ---------------------------------------------------------------------------


class CapabilityBase(BaseModel):
    """能力注册的基础字段定义，被 Create/Update/Read 共用。"""

    model_config = ConfigDict(from_attributes=True)

    type: CapabilityType = Field(description="能力类型：MODEL 模型服务 / MCP 工具协议 / FUNCTION HTTP 函数")
    code: str = Field(description="能力唯一编码，节点通过此 code 引用能力（如 'gpt-4o'、'approval-mcp'）")
    name: str = Field(description="能力显示名称，用于 UI 展示")
    description: str | None = Field(default=None, description="能力用途说明，FUNCTION 类型时会作为 Agent 工具描述")
    status: str = Field(default="active", description="能力状态：active 可用 / inactive 已停用")
    config_json: dict[str, Any] = Field(default_factory=dict, description="能力配置详情，按 type 不同结构不同（如模型的 api_host、MCP 的 url）")


class CapabilityCreate(CapabilityBase):
    pass


class CapabilityUpdate(CapabilityBase):
    pass


class CapabilityRead(TimestampsMixin, CapabilityBase):
    pass


class CapabilityDeleteResponse(BaseModel):
    """能力删除的响应。"""

    deleted: bool = Field(description="是否删除成功")
    capability_id: str = Field(description="被删除的能力 ID")


# ---------------------------------------------------------------------------
# Model provider schemas
# ---------------------------------------------------------------------------


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class ModelCatalogCapabilities(BaseModel):
    """模型能力标记，用于前端过滤和展示。"""

    vision: bool = Field(default=False, description="是否支持图像/视觉理解")
    reasoning: bool = Field(default=False, description="是否支持深度推理（如 o1/o3 系列）")
    tool_use: bool = Field(default=False, description="是否支持函数调用 / Tool Use")


class ModelCatalogItem(BaseModel):
    """单个模型的描述信息，支持多种历史数据格式兼容。

    apply_legacy_shape 负责将历史字段（model/name/type）映射到标准字段，
    使旧版 config_json 无需迁移即可正常读取。
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="模型标识（如 'gpt-4o'、'claude-3-opus'），作为 API 调用时的 model 参数")
    display_name: str | None = Field(default=None, description="模型展示名称，为空时前端使用 id 显示")
    model_type: str = Field(default="chat", description="模型类型：chat 对话 / embedding 向量 / image 图像生成等")
    capabilities: ModelCatalogCapabilities = Field(
        default_factory=ModelCatalogCapabilities, description="模型支持的能力标记"
    )
    context_window: int | None = Field(default=None, ge=1, description="模型上下文窗口大小（token 数）")
    max_output_tokens: int | None = Field(default=None, ge=1, description="模型单次最大输出 token 数")

    @model_validator(mode="before")
    @classmethod
    def apply_legacy_shape(cls, value: object) -> object:
        """兼容纯字符串格式和旧字段名格式的历史数据。"""
        if isinstance(value, str):
            return {"id": value}
        if not isinstance(value, dict):
            return value

        payload = dict(value)
        if not payload.get("id") and payload.get("model"):
            payload["id"] = payload["model"]
        if not payload.get("display_name") and payload.get("name"):
            payload["display_name"] = payload["name"]
        if not payload.get("model_type") and payload.get("type"):
            payload["model_type"] = payload["type"]
        return payload

    @field_validator("id", "display_name", "model_type", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalize_optional_string(str(value))


class ModelProviderConfig(BaseModel):
    """模型能力的完整配置结构，存储于 CapabilityRegistry.config_json。

    api_key_env：通过环境变量名引用密钥，避免将真实 API Key 写入数据库。
    apply_legacy_aliases：将旧版字段 base_url/default_model 映射到当前字段名。
    """

    model_config = ConfigDict(extra="allow")

    api_mode: ModelApiMode = Field(default=ModelApiMode.OPENAI_COMPATIBLE, description="API 协议模式，目前支持 OpenAI 兼容格式和 DeepSeek 兼容格式")
    api_key: str | None = Field(default=None, description="API 密钥明文，优先级高于 api_key_env")
    api_key_env: str | None = Field(default=None, description="API 密钥的环境变量名，运行时动态读取，避免明文入库")
    api_host: str | None = Field(default=None, description="模型服务地址（如 'https://api.openai.com'），为空时使用全局配置")
    api_path: str = Field(default="/chat/completions", description="API 请求路径，默认为 OpenAI Chat Completions 端点")
    auth_header_name: str = Field(default="Authorization", description="认证请求头名称，默认 'Authorization'。网关接入时可改为 'Authorization-Gateway'、'X-API-Key' 等自定义头")
    auth_header_scheme: str = Field(default="Bearer ", description="认证头值的前缀，最终发出 '<scheme><api_key>'。默认 'Bearer '；网关原样透传 token 时设为空字符串 ''")
    network_compatibility: bool = Field(default=False, description="网络兼容模式，开启后探测时放宽超时和重试策略")
    available_models: list[ModelCatalogItem] = Field(default_factory=list, description="该提供方支持的模型目录，用于前端下拉选择")
    model_name: str | None = Field(default=None, description="默认使用的模型名称，节点未指定时回退到此值")
    stream: bool = Field(default=False, description="是否启用流式响应")
    reasoning_effort: Literal["low", "medium", "high"] | None = Field(default=None, description="推理深度，仅部分模型（如 o1/o3）支持")
    max_tokens: int | None = Field(default=None, ge=1, description="单次请求最大输出 token 数")
    memory_compression_threshold: int = Field(default=32000, ge=1, description="Agent 记忆压缩触发阈值，超过后会压缩旧上下文")
    agent_execution_timeout_seconds: int = Field(default=300, ge=1, description="Agent 单轮执行总超时秒数，超过后当前工作流节点会失败并退出运行")

    @model_validator(mode="before")
    @classmethod
    def apply_legacy_aliases(cls, value: object) -> object:
        """将旧版字段名（base_url / default_model）兼容映射到当前字段名。"""
        if not isinstance(value, dict):
            return value

        payload = dict(value)
        if not payload.get("api_host") and payload.get("base_url"):
            payload["api_host"] = payload["base_url"]
        if not payload.get("model_name") and payload.get("default_model"):
            payload["model_name"] = payload["default_model"]
        return payload

    @field_validator("api_key", "api_key_env", "api_host", "model_name", mode="before")
    @classmethod
    def normalize_optional_string_fields(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalize_optional_string(str(value))

    @field_validator("api_path", mode="before")
    @classmethod
    def normalize_api_path(cls, value: object) -> str:
        normalized = _normalize_optional_string(
            str(value) if value is not None else None
        )
        if not normalized:
            return "/chat/completions"
        # 确保路径始终以 "/" 开头
        if not normalized.startswith("/"):
            return f"/{normalized}"
        return normalized

    @field_validator("auth_header_name", mode="before")
    @classmethod
    def normalize_auth_header_name(cls, value: object) -> str:
        if value is None:
            return "Authorization"
        normalized = str(value).strip()
        return normalized or "Authorization"

    @field_validator("auth_header_scheme", mode="before")
    @classmethod
    def normalize_auth_header_scheme(cls, value: object) -> str:
        # 允许显式空字符串（网关直接透传 token），所以这里不去 strip 末尾空格
        if value is None:
            return "Bearer "
        return str(value)

    @field_validator("available_models", mode="before")
    @classmethod
    def normalize_available_models(cls, value: object) -> list[ModelCatalogItem]:
        """去重并过滤无效模型 ID，防止重复模型条目干扰下拉选择。"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("available_models must be a list.")

        normalized: list[ModelCatalogItem] = []
        seen: set[str] = set()
        for item in value:
            candidate = ModelCatalogItem.model_validate(item)
            if not candidate.id or candidate.id in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate.id)
        return normalized


class ModelProviderProbeRequest(BaseModel):
    """模型服务连通性探测请求，用于创建/更新能力前的预验证。"""

    model_config = ConfigDict(extra="allow")

    api_mode: ModelApiMode = Field(default=ModelApiMode.OPENAI_COMPATIBLE, description="API 协议模式")
    api_key: str | None = Field(default=None, description="API 密钥，用于探测时的身份认证")
    api_key_env: str | None = Field(default=None, description="API 密钥的环境变量名")
    api_host: str = Field(description="待探测的模型服务地址")
    api_path: str = Field(default="/chat/completions", description="API 请求路径")
    auth_header_name: str = Field(default="Authorization", description="认证请求头名称，默认 'Authorization'")
    auth_header_scheme: str = Field(default="Bearer ", description="认证头值前缀，最终发出 '<scheme><api_key>'")
    network_compatibility: bool = Field(default=False, description="网络兼容模式")

    @field_validator("api_key", "api_key_env", "api_host", mode="before")
    @classmethod
    def normalize_required_string_fields(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalize_optional_string(str(value))

    @field_validator("api_path", mode="before")
    @classmethod
    def normalize_probe_path(cls, value: object) -> str:
        normalized = _normalize_optional_string(
            str(value) if value is not None else None
        )
        if not normalized:
            return "/chat/completions"
        if not normalized.startswith("/"):
            return f"/{normalized}"
        return normalized

    @field_validator("auth_header_name", mode="before")
    @classmethod
    def normalize_probe_auth_header_name(cls, value: object) -> str:
        if value is None:
            return "Authorization"
        normalized = str(value).strip()
        return normalized or "Authorization"

    @field_validator("auth_header_scheme", mode="before")
    @classmethod
    def normalize_probe_auth_header_scheme(cls, value: object) -> str:
        if value is None:
            return "Bearer "
        return str(value)


class ModelProviderCheckResponse(BaseModel):
    """模型服务连通性检查的响应。"""

    ok: bool = Field(description="连通性检查是否通过")
    api_mode: ModelApiMode = Field(description="使用的 API 协议模式")
    api_host: str = Field(description="被检查的服务地址")
    api_path: str = Field(description="被检查的 API 路径")
    models_endpoint: str = Field(description="实际请求的模型列表端点完整 URL")
    model_count: int = Field(description="探测到的可用模型数量")
    message: str = Field(description="检查结果描述信息")


class ModelProviderDiscoverResponse(BaseModel):
    """模型发现的响应，返回该提供方支持的所有模型列表。"""

    api_mode: ModelApiMode = Field(description="使用的 API 协议模式")
    api_host: str = Field(description="服务地址")
    api_path: str = Field(description="API 路径")
    models_endpoint: str = Field(description="实际请求的模型列表端点完整 URL")
    models: list[str] = Field(default_factory=list, description="发现的模型 ID 列表")
