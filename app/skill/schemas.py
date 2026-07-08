"""技能 Pydantic Schema。

写入端只接受完整的 SKILL.md 原文 (source)，code 与 description
均由服务端解析 YAML frontmatter 后填充，避免双写漂移。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampsMixin


class SkillCreate(BaseModel):
    """新增技能 — 仅接受 SKILL.md 全文与状态。"""

    source: str = Field(min_length=1, description="完整 SKILL.md 原文（含 YAML frontmatter）")
    status: str = Field(default="active", description="active / inactive")


class SkillUpdate(BaseModel):
    """更新技能 — source 必填整段覆盖，状态可选。"""

    model_config = ConfigDict(from_attributes=True)

    source: str | None = Field(default=None, min_length=1)
    status: str | None = None


class SkillRead(TimestampsMixin):
    """读取响应 — 返回原始 source 与解析出的 code/description 衍生列。"""

    code: str = Field(description="frontmatter.name，全局唯一")
    description: str | None = Field(default=None, description="frontmatter.description")
    source: str = Field(description="完整 SKILL.md 原文")
    status: str = "active"
    created_by: str | None = None


class SkillListItem(TimestampsMixin):
    """列表响应的精简项 — 不返回完整 source 减小传输。"""

    code: str
    description: str | None = None
    status: str = "active"
    created_by: str | None = None


class SkillListResponse(BaseModel):
    items: list[SkillListItem]
    total: int


class SkillDeleteResponse(BaseModel):
    deleted: bool
    skill_id: str
