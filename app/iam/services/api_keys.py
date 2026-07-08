"""API Key 管理与认证服务。

Key 格式：<key_prefix>.<secret>
  - key_prefix：格式为 "agk_<hex12>"，唯一索引列，用于快速定位数据库记录
  - secret：32字节 URL-safe Base64 随机串，仅在创建时以明文返回

认证流程：
  1. 按 key_prefix 查表（O(1) 索引查询）
  2. 使用 HMAC-SHA256 比较 secret 哈希（常数时间，防时序攻击）
  3. 检查吊销状态和过期时间
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import UserApiKey
from app.domain.enums import UserStatus
from app.iam.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyRead,
    UserRead,
)
from app.iam.services.identity import UserService


# 所有 API Key 的前缀命名空间，用于快速区分令牌类型
API_KEY_PREFIX_NAMESPACE = "agk"


def _serialize_api_key(api_key: UserApiKey) -> ApiKeyRead:
    now = datetime.now(timezone.utc)
    # is_active 是计算属性：未吊销且未过期
    is_active = api_key.revoked_at is None and (
        api_key.expires_at is None or api_key.expires_at > now
    )
    return ApiKeyRead(
        id=api_key.id,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
        is_active=is_active,
    )


class ApiKeyService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.user_service = UserService()

    async def list_for_user(
        self, session: AsyncSession, user_id: str
    ) -> list[ApiKeyRead]:
        stmt = (
            sa.select(UserApiKey)
            .where(UserApiKey.user_id == user_id)
            .order_by(UserApiKey.created_at.desc())
        )
        api_keys = (await session.scalars(stmt)).all()
        return [_serialize_api_key(api_key) for api_key in api_keys]

    async def create_for_user(
        self,
        session: AsyncSession,
        user: UserRead,
        payload: ApiKeyCreateRequest,
    ) -> ApiKeyCreateResponse:
        key_prefix = await self._generate_key_prefix(session)
        secret = secrets.token_urlsafe(24)
        record = UserApiKey(
            user_id=user.id,
            name=payload.name,
            key_prefix=key_prefix,
            secret_hash=self._hash_secret(secret),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return ApiKeyCreateResponse(
            api_key=_serialize_api_key(record),
            # 仅此处以明文返回完整密钥，后续无法再次获取
            plain_text_key=f"{key_prefix}.{secret}",
        )

    async def delete_for_user(
        self, session: AsyncSession, user_id: str, key_id: str
    ) -> None:
        api_key = await self._get_owned_key(session, user_id, key_id)
        await session.delete(api_key)
        await session.commit()

    async def authenticate(self, session: AsyncSession, token: str) -> UserRead:
        """通过 API Key 认证用户，认证成功后更新最后使用时间。"""
        key_prefix, secret = self._parse_api_key(token)
        stmt = sa.select(UserApiKey).where(UserApiKey.key_prefix == key_prefix)
        api_key = (await session.scalars(stmt)).one_or_none()
        if api_key is None:
            raise self._invalid_api_key()
        if api_key.revoked_at is not None:
            raise self._invalid_api_key()
        if api_key.expires_at is not None and api_key.expires_at <= datetime.now(
            timezone.utc
        ):
            raise self._invalid_api_key()
        # 常数时间比较，防止通过响应时间推断哈希前缀
        if not hmac.compare_digest(api_key.secret_hash, self._hash_secret(secret)):
            raise self._invalid_api_key()

        try:
            user = await self.user_service.get(session, api_key.user_id)
        except LookupError as exc:
            raise self._invalid_api_key() from exc
        if user.status != UserStatus.ACTIVE:
            raise self._invalid_api_key(detail="User account is disabled.")

        api_key.last_used_at = datetime.now(timezone.utc)
        await session.commit()
        return user

    def looks_like_api_key(self, token: str) -> bool:
        """通过前缀快速判断令牌是否为 API Key 格式，避免不必要的签名验证。"""
        return token.startswith(f"{API_KEY_PREFIX_NAMESPACE}_")

    async def _generate_key_prefix(self, session: AsyncSession) -> str:
        """生成全局唯一的 key_prefix（碰撞概率极低，通常一次循环即可）。"""
        while True:
            candidate = f"{API_KEY_PREFIX_NAMESPACE}_{secrets.token_hex(6)}"
            exists = await session.scalar(
                sa.select(sa.func.count())
                .select_from(UserApiKey)
                .where(UserApiKey.key_prefix == candidate),
            )
            if not exists:
                return candidate

    async def _get_owned_key(
        self, session: AsyncSession, user_id: str, key_id: str
    ) -> UserApiKey:
        """获取属于指定用户的 API Key，防止越权访问。"""
        stmt = sa.select(UserApiKey).where(
            UserApiKey.id == key_id,
            UserApiKey.user_id == user_id,
        )
        api_key = (await session.scalars(stmt)).one_or_none()
        if api_key is None:
            raise LookupError(f"API key '{key_id}' not found.")
        return api_key

    def _parse_api_key(self, token: str) -> tuple[str, str]:
        """解析 key_prefix 和 secret，格式非法时直接抛 401。"""
        key_prefix, separator, secret = token.partition(".")
        if not separator or not key_prefix or not secret:
            raise self._invalid_api_key()
        if not key_prefix.startswith(f"{API_KEY_PREFIX_NAMESPACE}_"):
            raise self._invalid_api_key()
        return key_prefix, secret

    def _hash_secret(self, secret: str) -> str:
        """使用 HMAC-SHA256 和全局密钥对 secret 进行哈希，防止彩虹表攻击。"""
        return hashlib.sha256(
            f"{self.settings.auth_secret_key}:{secret}".encode("utf-8"),
        ).hexdigest()

    def _invalid_api_key(self, detail: str = "Invalid API key.") -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )
