from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.iam.schemas import (
    PermissionCreate,
    PermissionDeleteResponse,
    PermissionRead,
    PermissionUpdate,
)
from app.iam.services.identity import PermissionService


router = APIRouter()
service = PermissionService()


@router.get(
    "",
    response_model=list[PermissionRead],
    dependencies=[Depends(require_permission(PermissionCode.PERMISSIONS_READ))],
)
async def list_permissions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[PermissionRead]:
    return await service.list(session)


@router.get(
    "/{permission_id}",
    response_model=PermissionRead,
    dependencies=[Depends(require_permission(PermissionCode.PERMISSIONS_READ))],
)
async def get_permission(
    permission_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionRead:
    try:
        return await service.get(session, permission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "",
    response_model=PermissionRead,
    dependencies=[Depends(require_permission(PermissionCode.PERMISSIONS_CREATE))],
)
async def create_permission(
    payload: PermissionCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionRead:
    try:
        return await service.create(session, payload)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put(
    "/{permission_id}",
    response_model=PermissionRead,
    dependencies=[Depends(require_permission(PermissionCode.PERMISSIONS_UPDATE))],
)
async def update_permission(
    permission_id: str,
    payload: PermissionUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionRead:
    try:
        return await service.update(session, permission_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/{permission_id}",
    response_model=PermissionDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.PERMISSIONS_DELETE))],
)
async def delete_permission(
    permission_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionDeleteResponse:
    try:
        return await service.delete(session, permission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
