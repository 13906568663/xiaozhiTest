"""ORM 基础类与通用混入。

所有 SQLAlchemy 模型均应继承自 Base，并按需混入
UUIDPrimaryKeyMixin（主键）和 TimestampMixin（审计时间戳）。
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类，负责维护全局 metadata 注册表。"""


# 在 PostgreSQL 上使用原生 JSONB 类型以获得索引与操作符支持；
# 其他数据库回退到通用 JSON 类型，确保可移植性。
json_type = sa.JSON().with_variant(JSONB, "postgresql")


def generate_uuid() -> str:
    """生成字符串形式的 UUID4，作为主键默认值。"""
    return str(uuid4())


class UUIDPrimaryKeyMixin:
    """为模型提供字符串 UUID 主键。

    使用字符串而非原生 UUID 类型，以兼容不原生支持 UUID 的数据库驱动。
    """

    id: Mapped[str] = mapped_column(
        sa.String(36),
        primary_key=True,
        default=generate_uuid,
    )


class TimestampMixin:
    """为模型提供 created_at / updated_at 审计时间戳。

    时间由数据库服务器生成（server_default），避免应用层时钟偏差。
    updated_at 通过 onupdate 钩子在每次 UPDATE 时自动刷新。
    """

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
