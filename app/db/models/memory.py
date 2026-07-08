"""记忆管理 ORM 模型。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_type


class MemoryStore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_store"

    user_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    username: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    memory_type: Mapped[str] = mapped_column(sa.String(32), default="long_term")
    key: Mapped[str] = mapped_column(sa.String(256))
    content: Mapped[str] = mapped_column(sa.Text())
    metadata_json: Mapped[dict] = mapped_column(json_type, default=dict)
