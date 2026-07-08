"""跨域共享的基础 Pydantic Schema 定义。

这些类型被 IAM、Capabilities、Workflow 三个域共同引用，
因此放在 schemas/common.py 中而非某个具体域，避免循环导入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    BindingSource,
    CapabilityType,
    CompensationActionType,
    CompensationStatus,
    CompensationTrigger,
    NodeExecutorType,
    NodeMode,
    NodeRunStatus,
    TaskRunStatus,
    TemplateStatus,
    WakeType,
)


class ORMModel(BaseModel):
    """启用 from_attributes=True 的基类，允许从 SQLAlchemy ORM 实例直接构建 Schema。"""

    model_config = ConfigDict(from_attributes=True)


class CapabilityBinding(BaseModel):
    """节点对能力的引用绑定。

    source=GLOBAL 时，ref 为能力注册表中的 code，运行时由 CapabilityResolverService 解析。
    source=NODE 时，config 包含完整配置，无需查询注册表（节点级临时覆盖）。
    """

    source: BindingSource = Field(default=BindingSource.GLOBAL, description="绑定来源：GLOBAL 引用全局注册表；NODE 节点内联完整配置")
    ref: str | None = Field(default=None, description="能力引用标识，source=GLOBAL 时为注册表中的 code（如 'gpt-4o'）")
    config: dict[str, Any] = Field(default_factory=dict, description="能力配置，source=NODE 时为完整配置；source=GLOBAL 时可覆盖注册表默认值")


class AsyncNodeConfig(BaseModel):
    """节点 session 等待策略配置（历史命名为 AsyncNodeConfig，语义已归入 session stage）。

    仅当节点模板标记为 mode=async 时由前端发送，用于在 UI 层门控超时参数。
    实际运行时 session 的 wait_callback / wait_timer 由模型自主决策，
    此配置主要作为默认超时和 instance_id 提取规则。
    """

    callback_enabled: bool = Field(default=True, description="是否启用回调监听，关闭后节点派发即完成，不等待外部响应")
    instance_id_path: str = Field(default="$.instance_id", description="JSONPath 表达式，从外部系统响应中提取实例 ID 用于回调路由")
    timeout_seconds: int = Field(default=8 * 60 * 60, ge=1, description="等待回调的超时时间（秒），超时后触发超时处理和补偿")


class CompensationAction(BaseModel):
    """补偿动作定义，描述在节点失败/超时时要执行的操作。

    args_mapping：键值映射，将 context 中的字段绑定到补偿动作的参数，
    支持在不修改节点配置的情况下动态传参。
    """

    type: CompensationActionType = Field(description="补偿动作类型：MCP 调用 MCP 工具 / FUNCTION 调用 HTTP 函数")
    ref: str = Field(description="补偿动作引用的能力 code，用于查找注册表中的工具配置")
    config: dict[str, Any] = Field(default_factory=dict, description="补偿动作的配置（如 URL、超时等），与注册表配置合并使用")
    args_mapping: dict[str, Any] = Field(default_factory=dict, description="参数映射：将运行时 context/payload 中的字段绑定到补偿动作入参")


class CompensationRule(BaseModel):
    """节点补偿规则，定义触发条件和对应动作。

    trigger_on 为空列表时，补偿规则被忽略（等同于不配置补偿）。
    """

    trigger_on: list[CompensationTrigger] = Field(default_factory=list, description="触发补偿的条件列表：FAILED 节点失败时 / TIMEOUT 节点超时时")
    action: CompensationAction | None = Field(default=None, description="补偿动作定义，为空表示不执行任何补偿")


class TimestampsMixin(ORMModel):
    """为响应 Schema 提供 id / created_at / updated_at 字段的混入基类。"""

    id: str = Field(description="记录唯一 ID（UUID）")
    created_at: datetime = Field(description="创建时间（UTC）")
    updated_at: datetime = Field(description="最后更新时间（UTC）")


__all__ = [
    "AsyncNodeConfig",
    "BindingSource",
    "CapabilityBinding",
    "CapabilityType",
    "CompensationAction",
    "CompensationActionType",
    "CompensationRule",
    "CompensationStatus",
    "CompensationTrigger",
    "NodeExecutorType",
    "NodeMode",
    "NodeRunStatus",
    "ORMModel",
    "TaskRunStatus",
    "TemplateStatus",
    "TimestampsMixin",
    "WakeType",
]
