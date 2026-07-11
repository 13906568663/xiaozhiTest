"""动态工具集 REST API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_current_user, require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.iam.schemas import UserRead
from app.toolset.schemas import (
    DynamicToolCreate,
    DynamicToolDeleteResponse,
    DynamicToolListResponse,
    DynamicToolRead,
    DynamicToolUpdate,
)
from app.toolset.services import toolsets as toolset_service

router = APIRouter()


@router.get(
    "",
    response_model=DynamicToolListResponse,
    dependencies=[Depends(require_permission(PermissionCode.TOOLSETS_READ))],
)
async def list_dynamic_tools(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[str | None, Query(description="按名称模糊筛选")] = None,
    status: Annotated[str | None, Query(description="按状态精确筛选")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DynamicToolListResponse:
    items, total = await toolset_service.list_dynamic_tools(
        session,
        name=name,
        status=status,
        page=page,
        page_size=page_size,
    )
    return DynamicToolListResponse(
        items=[DynamicToolRead.model_validate(tool) for tool in items],
        total=total,
    )


@router.post(
    "",
    response_model=DynamicToolRead,
    dependencies=[Depends(require_permission(PermissionCode.TOOLSETS_WRITE))],
)
async def create_dynamic_tool(
    payload: DynamicToolCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_current_user)],
) -> DynamicToolRead:
    data = payload.model_dump()
    data["created_by"] = current_user.username
    tool = await toolset_service.create_dynamic_tool(session, data)
    await session.commit()
    await session.refresh(tool)
    return DynamicToolRead.model_validate(tool)


@router.get(
    "/{tool_id}",
    response_model=DynamicToolRead,
    dependencies=[Depends(require_permission(PermissionCode.TOOLSETS_READ))],
)
async def get_dynamic_tool(
    tool_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DynamicToolRead:
    tool = await toolset_service.get_dynamic_tool(session, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="动态工具不存在")
    return DynamicToolRead.model_validate(tool)


@router.put(
    "/{tool_id}",
    response_model=DynamicToolRead,
    dependencies=[Depends(require_permission(PermissionCode.TOOLSETS_WRITE))],
)
async def update_dynamic_tool(
    tool_id: str,
    payload: DynamicToolUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DynamicToolRead:
    data = payload.model_dump(exclude_unset=True)
    tool = await toolset_service.update_dynamic_tool(session, tool_id, data)
    if tool is None:
        raise HTTPException(status_code=404, detail="动态工具不存在")
    await session.commit()
    await session.refresh(tool)
    return DynamicToolRead.model_validate(tool)


@router.delete(
    "/{tool_id}",
    response_model=DynamicToolDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.TOOLSETS_WRITE))],
)
async def delete_dynamic_tool(
    tool_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DynamicToolDeleteResponse:
    deleted = await toolset_service.delete_dynamic_tool(session, tool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="动态工具不存在")
    await session.commit()
    return DynamicToolDeleteResponse(deleted=True, tool_id=tool_id)
