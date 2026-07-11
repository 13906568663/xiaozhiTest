"""动态工具集 Pydantic Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel, TimestampsMixin


class DynamicToolBase(ORMModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(description="工具显示名称")
    description: str | None = Field(default=None, description="工具说明")
    method: str = Field(
        default="POST", description="HTTP 方法：GET / POST / PUT / DELETE / PATCH"
    )
    url: str = Field(description="调用地址")
    headers: dict[str, Any] = Field(
        default_factory=dict, description="请求头（JSON 对象）"
    )
    parameters_schema: dict[str, Any] = Field(
        default_factory=dict, description="入参 JSON Schema"
    )
    status: str = Field(default="active", description="active / inactive")


class DynamicToolCreate(DynamicToolBase):
    pass


class DynamicToolUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    description: str | None = None
    method: str | None = None
    url: str | None = None
    headers: dict[str, Any] | None = None
    parameters_schema: dict[str, Any] | None = None
    status: str | None = None


class DynamicToolRead(TimestampsMixin, DynamicToolBase):
    last_invoked_at: datetime | None = Field(
        default=None, description="最近一次调用时间（UTC）"
    )
    created_by: str | None = Field(default=None, description="创建人标识")


class DynamicToolListResponse(BaseModel):
    items: list[DynamicToolRead]
    total: int


class DynamicToolDeleteResponse(BaseModel):
    deleted: bool = Field(description="是否删除成功")
    tool_id: str = Field(description="被删除的工具 ID")
