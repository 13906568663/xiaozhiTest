"""Capabilities 域 ORM 模型。

CapabilityRegistry 是平台统一的能力注册表，
支持三类能力：MODEL（LLM 模型配置）、MCP（MCP 协议工具）、FUNCTION（HTTP 函数）。
节点通过 code 引用能力，运行时动态解析为具体配置。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_type
from app.domain.enums import CapabilityType


class CapabilityRegistry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """平台能力注册表，统一管理模型、MCP 工具和 HTTP 函数的连接配置。

    config_json 的结构因 type 不同而异，服务层在写入前执行类型特定的校验与归一化。
    validate_strings=True 确保从数据库读取到的字符串枚举值通过校验，防止脏数据进入应用层。
    """

    __tablename__ = "capability_registry"

    type: Mapped[CapabilityType] = mapped_column(
        sa.Enum(
            CapabilityType,
            native_enum=False,
            create_constraint=True,
            # 读取时校验字符串是否为合法枚举值，防止历史脏数据导致运行时异常
            validate_strings=True,
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), default="active")
    # 敏感字段（如 API Key）存储前应在服务层加密；当前版本以明文存储，适用于本地开发
    config_json: Mapped[dict] = mapped_column(json_type, default=dict)
