"""认证服务，负责登录校验、令牌签发与当前用户身份解析。

令牌格式：<base64url(payload)>.<base64url(hmac-sha256-signature)>
这是一个轻量自实现的签名令牌，未遵循标准 JWT 格式，
优点是无第三方依赖，缺点是不支持标准 JWT 工具链（如 jwt.io 调试）。
若需接入第三方 SSO 或需要 jwks 验证，应替换为 python-jose 等标准库。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.enums import UserStatus
from app.iam.passwords import verify_password
from app.iam.schemas import AuthLoginResponse, UserRead
from app.iam.services.api_keys import ApiKeyService
from app.iam.services.identity import IdentityBootstrapService, UserService


class AuthService:
    """提供登录、令牌签发与当前用户解析能力。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_key_service = ApiKeyService()
        self.bootstrap_service = IdentityBootstrapService()
        self.user_service = UserService()

    async def login(
        self, session: AsyncSession, *, username: str, password: str
    ) -> AuthLoginResponse:
        # 登录时顺带执行引导初始化，确保首次请求时默认权限/角色/管理员均已创建
        await self.bootstrap_service.ensure_defaults(session)

        user = await self.user_service.get_by_username(session, username)
        # 用户不存在和密码错误统一返回相同错误，避免用户名枚举攻击
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled.",
            )

        access_token = self._issue_token(
            {
                "sub": user.id,
                "username": user.username,
                "exp": int(
                    (
                        datetime.now(timezone.utc)
                        + timedelta(hours=self.settings.auth_access_token_ttl_hours)
                    ).timestamp(),
                ),
            },
        )
        await self.user_service.mark_login_success(session, user)

        # 重新加载用户以获取包含最新 last_login_at 的完整 UserRead
        refreshed_user = await self.user_service.get(session, user.id)
        return AuthLoginResponse(
            access_token=access_token,
            user=refreshed_user,
        )

    async def get_current_user(self, session: AsyncSession, token: str) -> UserRead:
        """解析令牌（API Key 或 JWT-like token）并返回当前用户。"""
        # 通过前缀快速区分 API Key 和访问令牌，避免不必要的签名验证
        if self.api_key_service.looks_like_api_key(token):
            return await self.api_key_service.authenticate(session, token)

        payload = self._verify_token(token)
        user_id = str(payload["sub"])
        try:
            user = await self.user_service.get(session, user_id)
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            ) from exc
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is disabled.",
            )
        return user

    def _issue_token(self, payload: dict[str, Any]) -> str:
        """生成签名令牌：base64url(payload).base64url(hmac-sha256)。"""
        raw_payload = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        payload_part = base64.urlsafe_b64encode(raw_payload).decode("utf-8").rstrip("=")
        signature = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature_part = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
        return f"{payload_part}.{signature_part}"

    def _verify_token(self, token: str) -> dict[str, Any]:
        """校验令牌签名和过期时间，返回 payload 字典。"""
        try:
            payload_part, signature_part = token.split(".", 1)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            ) from exc

        expected_signature = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        actual_signature = self._decode_base64(signature_part)
        # 使用常数时间比较防止时序攻击
        if actual_signature is None or not hmac.compare_digest(
            expected_signature, actual_signature
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )

        payload_raw = self._decode_base64(payload_part)
        if payload_raw is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )

        try:
            payload = json.loads(payload_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            ) from exc

        if int(payload.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token expired.",
            )

        return payload

    def _decode_base64(self, value: str) -> bytes | None:
        """解码 URL-safe Base64，自动补全缺失的 '=' 填充符。"""
        remainder = len(value) % 4
        if remainder:
            value = value + ("=" * (4 - remainder))
        try:
            return base64.urlsafe_b64decode(value.encode("utf-8"))
        except (ValueError, TypeError, binascii.Error):
            return None
