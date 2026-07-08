from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.iam.schemas import RoleCreate, RoleDeleteResponse, RoleRead, RoleUpdate, UserRead
from app.iam.services.identity import RoleService


router = APIRouter()
service = RoleService()


@router.get(
    "",
    response_model=list[RoleRead],
    dependencies=[Depends(require_permission(PermissionCode.ROLES_READ))],
)
async def list_roles(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[RoleRead]:
    return await service.list(session)


@router.get(
    "/{role_id}",
    response_model=RoleRead,
    dependencies=[Depends(require_permission(PermissionCode.ROLES_READ))],
)
async def get_role(
    role_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RoleRead:
    try:
        return await service.get(session, role_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", response_model=RoleRead)
async def create_role(
    payload: RoleCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_permission(PermissionCode.ROLES_CREATE))],
    request: Request,
) -> RoleRead:
    try:
        return await service.create(session, payload)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: str,
    payload: RoleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_permission(PermissionCode.ROLES_UPDATE))],
    request: Request,
) -> RoleRead:
    try:
        return await service.update(session, role_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{role_id}", response_model=RoleDeleteResponse)
async def delete_role(
    role_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_permission(PermissionCode.ROLES_DELETE))],
    request: Request,
) -> RoleDeleteResponse:
    try:
        return await service.delete(session, role_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
