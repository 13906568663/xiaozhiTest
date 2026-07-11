"""动态工具集 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_type


class DynamicTool(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dynamic_tool"

    name: Mapped[str] = mapped_column(sa.String(128))
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    method: Mapped[str] = mapped_column(sa.String(16), default="POST")
    url: Mapped[str] = mapped_column(sa.String(512))
    headers: Mapped[dict] = mapped_column(json_type, default=dict)
    parameters_schema: Mapped[dict] = mapped_column(json_type, default=dict)
    status: Mapped[str] = mapped_column(sa.String(16), default="active")
    last_invoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
