"""记忆管理 Pydantic Schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import TimestampsMixin


class MemoryStoreCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    username: str | None = Field(default=None, max_length=64)
    memory_type: str = Field(default="long_term", max_length=32)
    key: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MemoryStoreUpdate(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    memory_type: str | None = Field(default=None, max_length=32)
    key: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = None
    metadata_json: dict[str, Any] | None = None


class MemoryStoreRead(TimestampsMixin):
    user_id: str
    username: str | None = None
    memory_type: str = "long_term"
    key: str
    content: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MemoryStoreListResponse(BaseModel):
    items: list[MemoryStoreRead]
    total: int


class MemoryStoreDeleteResponse(BaseModel):
    deleted: bool
    memory_id: str


class MemoryUserDeleteResponse(BaseModel):
    deleted: bool
    user_id: str
    deleted_count: int
