"""技能（SKILL.md）ORM 模型。

Skill 以原始 SKILL.md 文本形式存储在 source 列，code/description 仅作为列表
检索的衍生列，保存时由服务端解析 YAML frontmatter 自动填充。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    source: Mapped[str] = mapped_column(sa.Text(), default="", nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), default="active", nullable=False)
    created_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
