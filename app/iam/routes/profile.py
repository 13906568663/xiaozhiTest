from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_current_user
from app.db.session import get_db_session
from app.iam.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    PasswordChangeRequest,
    ProfileRead,
    UserRead,
)
from app.iam.services.api_keys import ApiKeyService


router = APIRouter()
api_key_service = ApiKeyService()


@router.get("", response_model=ProfileRead)
async def get_profile(
    current_user: Annotated[UserRead, Depends(require_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProfileRead:
    return ProfileRead(
        user=current_user,
        api_keys=await api_key_service.list_for_user(session, current_user.id),
    )


@router.put("/password")
async def change_password(
    payload: PasswordChangeRequest,
    current_user: Annotated[UserRead, Depends(require_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    from app.db.models.iam import UserAccount
    from app.iam.passwords import hash_password, verify_password

    user = await session.get(UserAccount, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    user.password_hash = hash_password(payload.new_password)
    await session.commit()
    return {"success": True, "message": "密码修改成功"}


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    current_user: Annotated[UserRead, Depends(require_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyCreateResponse:
    return await api_key_service.create_for_user(session, current_user, payload)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    current_user: Annotated[UserRead, Depends(require_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    try:
        await api_key_service.delete_for_user(session, current_user.id, key_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
