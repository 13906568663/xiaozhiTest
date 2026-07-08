"""记忆管理 REST API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.memory.schemas import (
    MemoryStoreCreate,
    MemoryStoreDeleteResponse,
    MemoryStoreListResponse,
    MemoryStoreRead,
    MemoryStoreUpdate,
    MemoryUserDeleteResponse,
)
from app.memory.services import memories as memory_service

router = APIRouter()


@router.post(
    "",
    response_model=MemoryStoreRead,
    dependencies=[Depends(require_permission(PermissionCode.MEMORY_WRITE))],
)
async def create_memory(
    payload: MemoryStoreCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryStoreRead:
    row = await memory_service.create_memory_store(session, payload.model_dump())
    await session.commit()
    return MemoryStoreRead.model_validate(row)


@router.put(
    "/{memory_id}",
    response_model=MemoryStoreRead,
    dependencies=[Depends(require_permission(PermissionCode.MEMORY_WRITE))],
)
async def update_memory(
    memory_id: str,
    payload: MemoryStoreUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryStoreRead:
    row = await memory_service.update_memory_store(
        session, memory_id, payload.model_dump(exclude_unset=True),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    await session.commit()
    return MemoryStoreRead.model_validate(row)


@router.get(
    "",
    response_model=MemoryStoreListResponse,
    dependencies=[Depends(require_permission(PermissionCode.MEMORY_READ))],
)
async def list_memories(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user_id: Annotated[str | None, Query(max_length=36)] = None,
    memory_type: Annotated[str | None, Query(max_length=32)] = None,
    keyword: Annotated[str | None, Query(max_length=256)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MemoryStoreListResponse:
    items, total = await memory_service.list_memory_stores(
        session,
        user_id=user_id or None,
        memory_type=memory_type,
        keyword=keyword,
        skip=skip,
        limit=limit,
    )
    return MemoryStoreListResponse(
        items=[MemoryStoreRead.model_validate(m) for m in items],
        total=total,
    )


@router.get(
    "/{memory_id}",
    response_model=MemoryStoreRead,
    dependencies=[Depends(require_permission(PermissionCode.MEMORY_READ))],
)
async def get_memory(
    memory_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryStoreRead:
    row = await memory_service.get_memory_store(session, memory_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return MemoryStoreRead.model_validate(row)


@router.delete(
    "/user/{user_id}",
    response_model=MemoryUserDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.MEMORY_WRITE))],
)
async def delete_memories_for_user(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryUserDeleteResponse:
    count = await memory_service.delete_memory_stores_for_user(session, user_id)
    await session.commit()
    return MemoryUserDeleteResponse(
        deleted=True,
        user_id=user_id,
        deleted_count=count,
    )


@router.delete(
    "/{memory_id}",
    response_model=MemoryStoreDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.MEMORY_WRITE))],
)
async def delete_memory(
    memory_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryStoreDeleteResponse:
    deleted = await memory_service.delete_memory_store(session, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在")
    await session.commit()
    return MemoryStoreDeleteResponse(deleted=True, memory_id=memory_id)
