"""动态工具集业务逻辑。"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.toolset import DynamicTool


async def list_dynamic_tools(
    session: AsyncSession,
    *,
    name: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DynamicTool], int]:
    filters = []
    if name:
        filters.append(DynamicTool.name.ilike(f"%{name}%"))
    if status:
        filters.append(DynamicTool.status == status)

    base = sa.select(DynamicTool)
    count_stmt = sa.select(sa.func.count()).select_from(DynamicTool)
    if filters:
        base = base.where(*filters)
        count_stmt = count_stmt.where(*filters)

    total = int(await session.scalar(count_stmt) or 0)
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 100)
    offset = (safe_page - 1) * safe_size

    stmt = base.order_by(DynamicTool.created_at.desc()).offset(offset).limit(safe_size)
    result = await session.scalars(stmt)
    return list(result.all()), total


async def get_dynamic_tool(
    session: AsyncSession, tool_id: str
) -> DynamicTool | None:
    return await session.get(DynamicTool, tool_id)


async def create_dynamic_tool(
    session: AsyncSession, data: dict[str, Any]
) -> DynamicTool:
    tool = DynamicTool(**data)
    session.add(tool)
    await session.flush()
    return tool


async def update_dynamic_tool(
    session: AsyncSession, tool_id: str, data: dict[str, Any]
) -> DynamicTool | None:
    tool = await session.get(DynamicTool, tool_id)
    if tool is None:
        return None
    for key, value in data.items():
        setattr(tool, key, value)
    await session.flush()
    return tool


async def delete_dynamic_tool(session: AsyncSession, tool_id: str) -> bool:
    tool = await session.get(DynamicTool, tool_id)
    if tool is None:
        return False
    await session.delete(tool)
    await session.flush()
    return True
