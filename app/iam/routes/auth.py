from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AUTH_COOKIE_NAME, require_current_user
from app.db.session import get_db_session
from app.iam.schemas import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    UserRead,
)
from app.iam.services.auth import AuthService


router = APIRouter()
service = AuthService()


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=service.settings.auth_access_token_ttl_hours * 60 * 60,
        httponly=True,
        secure=service.settings.auth_cookie_secure,
        samesite=service.settings.auth_cookie_samesite,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        secure=service.settings.auth_cookie_secure,
        samesite=service.settings.auth_cookie_samesite,
    )


@router.post("/login", response_model=AuthLoginResponse)
async def login(
    payload: AuthLoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> AuthLoginResponse:
    auth_response = await service.login(
        session, username=payload.username, password=payload.password
    )
    _set_auth_cookie(response, auth_response.access_token)
    return auth_response


@router.get("/me", response_model=UserRead)
async def me(
    current_user: Annotated[UserRead, Depends(require_current_user)],
) -> UserRead:
    return current_user


@router.post("/logout", response_model=AuthLogoutResponse)
async def logout(
    response: Response,
    current_user: Annotated[UserRead, Depends(require_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> AuthLogoutResponse:
    _clear_auth_cookie(response)
    return AuthLogoutResponse()
