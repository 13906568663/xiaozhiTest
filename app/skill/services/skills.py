"""技能业务逻辑。

主要职责：
  - parse_skill_source: 解析 SKILL.md 的 YAML frontmatter（name / description），
    返回 (metadata, body)；body 为去除 frontmatter 后的 markdown 正文
  - 标准 CRUD
  - get_bodies_by_codes: 供 CapabilityResolverService 在解析节点时拉取技能正文
"""

from __future__ import annotations

import re

import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.skill import Skill


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
MAX_SOURCE_BYTES = 50 * 1024


class SkillSourceError(ValueError):
    """SKILL.md 解析或校验失败。"""


def parse_skill_source(source: str) -> tuple[dict, str]:
    """从 SKILL.md 原文中解析 YAML frontmatter 与正文。

    返回 (metadata_dict, body_markdown)。若没有 frontmatter 或解析失败，
    抛出 SkillSourceError。
    """
    if not source or not source.strip():
        raise SkillSourceError("SKILL.md 内容不能为空")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SkillSourceError(f"SKILL.md 超过 {MAX_SOURCE_BYTES // 1024}KB 上限")

    match = FRONTMATTER_RE.match(source)
    if match is None:
        raise SkillSourceError(
            "缺少 frontmatter；SKILL.md 必须以 '---' 包裹 YAML 元信息开头",
        )

    raw_meta = match.group(1)
    body = source[match.end():].lstrip("\n")

    try:
        meta = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError as exc:
        raise SkillSourceError(f"frontmatter YAML 解析失败：{exc}") from exc

    if not isinstance(meta, dict):
        raise SkillSourceError("frontmatter 必须是键值对（YAML 映射）")

    name = meta.get("name")
    if not isinstance(name, str) or not SKILL_NAME_PATTERN.match(name):
        raise SkillSourceError(
            "frontmatter.name 必填，且仅允许小写字母、数字、连字符，最长 64 字符",
        )

    description = meta.get("description")
    if description is not None and not isinstance(description, str):
        raise SkillSourceError("frontmatter.description 必须是字符串")

    return meta, body


def extract_code_and_description(source: str) -> tuple[str, str | None]:
    """便捷封装：仅取 code 和 description。"""
    meta, _ = parse_skill_source(source)
    desc = meta.get("description")
    desc_clean = (desc or "").strip() or None
    return meta["name"], desc_clean


async def list_skills(
    session: AsyncSession,
    *,
    code: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Skill], int]:
    filters = []
    if code:
        filters.append(Skill.code.ilike(f"%{code}%"))
    if status:
        filters.append(Skill.status == status)

    base = sa.select(Skill)
    count_stmt = sa.select(sa.func.count()).select_from(Skill)
    if filters:
        base = base.where(*filters)
        count_stmt = count_stmt.where(*filters)

    total = int(await session.scalar(count_stmt) or 0)

    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 200)
    offset = (safe_page - 1) * safe_size

    stmt = base.order_by(Skill.created_at.desc()).offset(offset).limit(safe_size)
    result = await session.scalars(stmt)
    return list(result.all()), total


async def get_skill(session: AsyncSession, skill_id: str) -> Skill | None:
    return await session.get(Skill, skill_id)


async def get_skill_by_code(session: AsyncSession, code: str) -> Skill | None:
    stmt = sa.select(Skill).where(Skill.code == code)
    return await session.scalar(stmt)


async def create_skill(
    session: AsyncSession,
    *,
    source: str,
    status: str,
    created_by: str | None,
) -> Skill:
    code, description = extract_code_and_description(source)
    existing = await get_skill_by_code(session, code)
    if existing is not None:
        raise SkillSourceError(f"技能编码 '{code}' 已存在")

    skill = Skill(
        code=code,
        description=description,
        source=source,
        status=status,
        created_by=created_by,
    )
    session.add(skill)
    await session.flush()
    return skill


async def update_skill(
    session: AsyncSession,
    skill_id: str,
    *,
    source: str | None,
    status: str | None,
) -> Skill | None:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        return None

    if source is not None:
        code, description = extract_code_and_description(source)
        if code != skill.code:
            collision = await get_skill_by_code(session, code)
            if collision is not None and collision.id != skill.id:
                raise SkillSourceError(f"技能编码 '{code}' 已存在")
        skill.code = code
        skill.description = description
        skill.source = source

    if status is not None:
        skill.status = status

    await session.flush()
    return skill


async def delete_skill(session: AsyncSession, skill_id: str) -> bool:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        return False
    await session.delete(skill)
    await session.flush()
    return True


async def get_bodies_by_codes(
    session: AsyncSession,
    codes: list[str],
) -> dict[str, str]:
    """按 code 拉取启用状态的技能，返回 {code: body_markdown}。

    丢失或停用的技能静默跳过，避免引用方因依赖删除而运行失败。
    """
    if not codes:
        return {}
    unique = list(dict.fromkeys(c for c in codes if c))
    if not unique:
        return {}

    stmt = sa.select(Skill).where(
        Skill.code.in_(unique),
        Skill.status == "active",
    )
    rows = (await session.scalars(stmt)).all()

    out: dict[str, str] = {}
    for row in rows:
        try:
            _, body = parse_skill_source(row.source)
        except SkillSourceError:
            continue
        out[row.code] = body
    return out


async def get_skills_with_meta(
    session: AsyncSession,
    codes: list[str],
) -> list[dict]:
    """按 code 拉取启用状态的技能，返回 [{code, description, body}, ...]。

    保留传入 codes 的去重顺序，便于 resolver 按用户配置顺序拼接；
    停用或解析失败的技能静默跳过。
    """
    if not codes:
        return []
    unique = list(dict.fromkeys(c for c in codes if c))
    if not unique:
        return []

    stmt = sa.select(Skill).where(
        Skill.code.in_(unique),
        Skill.status == "active",
    )
    rows = {row.code: row for row in (await session.scalars(stmt)).all()}

    out: list[dict] = []
    for code in unique:
        row = rows.get(code)
        if row is None:
            continue
        try:
            _, body = parse_skill_source(row.source)
        except SkillSourceError:
            continue
        out.append(
            {
                "code": row.code,
                "description": row.description or "",
                "body": body,
            }
        )
    return out
