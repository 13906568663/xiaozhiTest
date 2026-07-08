from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.core.config import get_settings
from app.iam.schemas import UserRead
from app.iam.services.auth import AuthService


AUTH_COOKIE_NAME = get_settings().auth_cookie_name

bearer_scheme = HTTPBearer(auto_error=False)
auth_service = AuthService()


def _resolve_access_token(
    credentials: HTTPAuthorizationCredentials | None,
    api_key_header: str | None,
    cookie_token: str | None,
) -> str:
    """优先读取 Bearer Token，其次回退到会话 Cookie。"""
    if (
        credentials
        and credentials.scheme.lower() == "bearer"
        and credentials.credentials
    ):
        return credentials.credentials

    if api_key_header:
        return api_key_header

    if cookie_token:
        return cookie_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


async def require_current_user(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    api_key_header: Annotated[str | None, Header(alias="X-API-Key")] = None,
    cookie_token: Annotated[str | None, Cookie(alias=AUTH_COOKIE_NAME)] = None,
) -> UserRead:
    """统一鉴权依赖：解析令牌并加载当前用户。"""
    token = _resolve_access_token(credentials, api_key_header, cookie_token)
    return await auth_service.get_current_user(session, token)


def user_has_permission(user: UserRead, permission_code: str) -> bool:
    """检查用户是否具备指定权限码。"""
    if user.is_superuser:
        return True
    return any(permission.code == permission_code for permission in user.permissions)


def require_permission(permission_code: str) -> Callable[..., Awaitable[UserRead]]:
    """返回 FastAPI 依赖函数，用于声明式权限校验。"""

    async def dependency(
        current_user: Annotated[UserRead, Depends(require_current_user)],
    ) -> UserRead:
        if user_has_permission(current_user, permission_code):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission '{permission_code}'.",
        )

    return dependency
