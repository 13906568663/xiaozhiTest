from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.iam.schemas import (
    UserCreate,
    UserDeleteResponse,
    UserListItem,
    UserRead,
    UserUpdate,
)
from app.iam.services.identity import UserService


router = APIRouter()
service = UserService()


@router.get(
    "",
    response_model=list[UserListItem],
    dependencies=[Depends(require_permission(PermissionCode.USERS_READ))],
)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[UserListItem]:
    return await service.list(session)


@router.post("", response_model=UserRead)
async def create_user(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_permission(PermissionCode.USERS_CREATE))],
    request: Request,
) -> UserRead:
    try:
        return await service.create(session, payload)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_permission(PermissionCode.USERS_READ))],
)
async def get_user(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    try:
        return await service.get(session, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_permission(PermissionCode.USERS_UPDATE))],
    request: Request,
) -> UserRead:
    try:
        return await service.update(session, user_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{user_id}", response_model=UserDeleteResponse)
async def delete_user(
    user_id: str,
    current_user: Annotated[
        UserRead, Depends(require_permission(PermissionCode.USERS_DELETE))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> UserDeleteResponse:
    try:
        return await service.delete(session, user_id, acting_user_id=current_user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
