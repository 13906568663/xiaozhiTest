"""IAM 身份服务层。

包含三类服务：
  - IdentityBootstrapService：系统引导初始化，幂等写入默认权限/角色/管理员
  - UserService / RoleService / PermissionService：CRUD 操作

有效权限计算逻辑（_effective_permission_models）：
  1. 收集用户所有激活角色中的权限（角色权限集）
  2. 追加直接 ALLOW 授权（可覆盖或补充角色权限）
  3. 删除直接 DENY 授权对应的权限（精确撤销）
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import (
    Permission,
    Role,
    RolePermissionBinding,
    UserAccount,
    UserPermissionGrant,
    UserRoleBinding,
)
from app.domain.enums import PermissionEffect, RoleStatus, UserStatus
from app.domain.permissions import (
    DEFAULT_PERMISSION_DEFINITIONS,
    DEFAULT_ROLE_DEFINITIONS,
    DEFAULT_ROLE_PERMISSION_CODES,
    RoleCode,
)
from app.iam.passwords import hash_password
from app.iam.schemas import (
    PermissionRead,
    RoleRead,
    RoleSummaryRead,
    UserCreate,
    UserDeleteResponse,
    UserListItem,
    UserPermissionGrantInput,
    UserPermissionGrantRead,
    UserRead,
    UserUpdate,
)


# 预定义的深度关联加载选项，避免懒加载触发 N+1 查询
# 用户 -> 角色绑定 -> 角色 -> 角色权限绑定 -> 权限
# 用户 -> 直接权限授予 -> 权限
USER_LOAD_OPTIONS = (
    selectinload(UserAccount.role_bindings)
    .selectinload(UserRoleBinding.role)
    .selectinload(Role.permission_bindings)
    .selectinload(RolePermissionBinding.permission),
    selectinload(UserAccount.direct_permission_grants).selectinload(
        UserPermissionGrant.permission
    ),
)

ROLE_LOAD_OPTIONS = (
    selectinload(Role.permission_bindings).selectinload(
        RolePermissionBinding.permission
    ),
)


def _serialize_permission(permission: Permission) -> PermissionRead:
    return PermissionRead.model_validate(permission)


def _serialize_role_summary(role: Role) -> RoleSummaryRead:
    return RoleSummaryRead.model_validate(role)


def _effective_permission_models(user: UserAccount) -> list[Permission]:
    """计算用户的有效权限集合（角色权限 ∪ 直接允许 − 直接拒绝）。

    已禁用角色的权限不计入有效集合。
    直接 DENY 授权优先于角色继承的 ALLOW，实现细粒度权限撤销。
    """
    role_permissions: dict[str, Permission] = {}
    for binding in user.role_bindings:
        if binding.role.status != RoleStatus.ACTIVE:
            continue
        for permission_binding in binding.role.permission_bindings:
            role_permissions[permission_binding.permission.code] = (
                permission_binding.permission
            )

    direct_allow: dict[str, Permission] = {}
    direct_deny_codes: set[str] = set()
    for grant in user.direct_permission_grants:
        if grant.effect == PermissionEffect.DENY:
            direct_deny_codes.add(grant.permission.code)
            continue
        direct_allow[grant.permission.code] = grant.permission

    effective = {**role_permissions, **direct_allow}
    for code in direct_deny_codes:
        effective.pop(code, None)

    return sorted(effective.values(), key=lambda item: item.code)


def serialize_user(user: UserAccount) -> UserRead:
    """将 ORM UserAccount 对象序列化为带完整权限信息的 UserRead Schema。"""
    roles = sorted(
        (_serialize_role_summary(binding.role) for binding in user.role_bindings),
        key=lambda item: item.code,
    )
    direct_permissions = sorted(
        (
            UserPermissionGrantRead(
                effect=grant.effect,
                permission=_serialize_permission(grant.permission),
            )
            for grant in user.direct_permission_grants
        ),
        key=lambda item: item.permission.code,
    )
    permissions = [
        _serialize_permission(permission)
        for permission in _effective_permission_models(user)
    ]
    return UserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        phone=user.phone,
        department=user.department,
        status=user.status,
        is_superuser=user.is_superuser,
        last_login_at=user.last_login_at,
        roles=roles,
        direct_permissions=direct_permissions,
        permissions=permissions,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def serialize_user_list_item(user: UserAccount) -> UserListItem:
    """将 ORM UserAccount 序列化为列表摘要（不含直接权限和有效权限详情）。"""
    return UserListItem(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        phone=user.phone,
        department=user.department,
        status=user.status,
        is_superuser=user.is_superuser,
        last_login_at=user.last_login_at,
        roles=sorted(
            (_serialize_role_summary(binding.role) for binding in user.role_bindings),
            key=lambda item: item.code,
        ),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class IdentityBootstrapService:
    """系统引导初始化服务，幂等地确保默认权限、角色和管理员账号存在。

    所有操作均为"不存在才插入"语义，可安全地多次调用，
    支持在新增权限定义后重启服务时自动补全缺失数据。
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    async def ensure_defaults(self, session: AsyncSession) -> None:
        await self._ensure_permissions(session)
        await self._ensure_roles(session)
        await self._ensure_role_permissions(session)
        await self._ensure_bootstrap_admin(session)
        await session.commit()

    async def _ensure_permissions(self, session: AsyncSession) -> None:
        existing_codes = {
            code for code in (await session.scalars(sa.select(Permission.code))).all()
        }
        for definition in DEFAULT_PERMISSION_DEFINITIONS:
            if definition.code in existing_codes:
                continue
            session.add(
                Permission(
                    code=definition.code,
                    resource=definition.resource,
                    action=definition.action,
                    type=definition.type,
                    description=definition.description,
                ),
            )
        await session.flush()

    async def _ensure_roles(self, session: AsyncSession) -> None:
        existing_codes = {
            code for code in (await session.scalars(sa.select(Role.code))).all()
        }
        for definition in DEFAULT_ROLE_DEFINITIONS:
            if definition.code in existing_codes:
                continue
            session.add(
                Role(
                    code=definition.code,
                    name=definition.name,
                    description=definition.description,
                    status=RoleStatus.ACTIVE,
                    is_system=definition.is_system,
                ),
            )
        await session.flush()

    async def _ensure_role_permissions(self, session: AsyncSession) -> None:
        roles = {
            role.code: role for role in (await session.scalars(sa.select(Role))).all()
        }
        permissions = {
            permission.code: permission
            for permission in (await session.scalars(sa.select(Permission))).all()
        }
        # 先加载已有的角色-权限对，避免重复插入触发唯一约束错误
        existing_pairs = {
            (role_code, permission_code)
            for role_code, permission_code in (
                await session.execute(
                    sa.select(Role.code, Permission.code)
                    .join(
                        RolePermissionBinding, RolePermissionBinding.role_id == Role.id
                    )
                    .join(
                        Permission, Permission.id == RolePermissionBinding.permission_id
                    ),
                )
            ).all()
        }

        for role_code, permission_codes in DEFAULT_ROLE_PERMISSION_CODES.items():
            role = roles.get(role_code)
            if role is None:
                continue
            for permission_code in permission_codes:
                permission = permissions.get(permission_code)
                if permission is None:
                    continue
                if (role_code, permission_code) in existing_pairs:
                    continue
                session.add(
                    RolePermissionBinding(
                        role_id=role.id,
                        permission_id=permission.id,
                    ),
                )
        await session.flush()

    async def _ensure_bootstrap_admin(self, session: AsyncSession) -> None:
        # 仅当数据库完全没有用户时才创建引导管理员，避免重复创建
        user_count = await session.scalar(
            sa.select(sa.func.count()).select_from(UserAccount)
        )
        if user_count and user_count > 0:
            return

        admin_role = await session.scalar(
            sa.select(Role).where(Role.code == RoleCode.PLATFORM_ADMIN),
        )
        if admin_role is None:
            return

        user = UserAccount(
            username=self.settings.admin_username,
            display_name=self.settings.admin_display_name,
            password_hash=hash_password(self.settings.admin_password),
            status=UserStatus.ACTIVE,
            is_superuser=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserRoleBinding(
                user_id=user.id,
                role_id=admin_role.id,
            ),
        )
        await session.flush()


class RoleService:
    async def list(self, session: AsyncSession) -> list[RoleRead]:
        stmt = (
            sa.select(Role).options(*ROLE_LOAD_OPTIONS).order_by(Role.created_at.asc())
        )
        roles = (await session.scalars(stmt)).unique().all()
        return [
            RoleRead(
                **RoleSummaryRead.model_validate(role).model_dump(),
                permissions=sorted(
                    (
                        _serialize_permission(binding.permission)
                        for binding in role.permission_bindings
                    ),
                    key=lambda item: item.code,
                ),
            )
            for role in roles
        ]

    async def get(self, session: AsyncSession, role_id: str) -> RoleRead:
        stmt = sa.select(Role).where(Role.id == role_id).options(*ROLE_LOAD_OPTIONS)
        role = (await session.scalars(stmt)).unique().one_or_none()
        if role is None:
            raise LookupError(f"Role '{role_id}' not found.")
        return RoleRead(
            **RoleSummaryRead.model_validate(role).model_dump(),
            permissions=sorted(
                (_serialize_permission(binding.permission) for binding in role.permission_bindings),
                key=lambda item: item.code,
            ),
        )

    async def create(self, session: AsyncSession, payload: "RoleCreate") -> RoleRead:
        role = Role(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            status=RoleStatus.ACTIVE,
            is_system=False,
        )
        session.add(role)
        await session.flush()

        if payload.permission_ids:
            perms = (
                await session.scalars(
                    sa.select(Permission).where(Permission.id.in_(payload.permission_ids))
                )
            ).all()
            perm_map = {p.id: p for p in perms}
            missing = [pid for pid in payload.permission_ids if pid not in perm_map]
            if missing:
                await session.rollback()
                raise LookupError(f"Permissions not found: {', '.join(missing)}")
            for perm in perms:
                session.add(RolePermissionBinding(role_id=role.id, permission_id=perm.id))

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError(f"Role code '{payload.code}' already exists.") from exc
        return await self.get(session, role.id)

    async def update(self, session: AsyncSession, role_id: str, payload: "RoleUpdate") -> RoleRead:
        stmt = sa.select(Role).where(Role.id == role_id).options(*ROLE_LOAD_OPTIONS)
        role = (await session.scalars(stmt)).unique().one_or_none()
        if role is None:
            raise LookupError(f"Role '{role_id}' not found.")

        if payload.name is not None:
            role.name = payload.name
        if payload.description is not None:
            role.description = payload.description
        if payload.status is not None:
            role.status = payload.status
        if payload.permission_ids is not None:
            await session.execute(
                sa.delete(RolePermissionBinding).where(RolePermissionBinding.role_id == role.id)
            )
            if payload.permission_ids:
                perms = (
                    await session.scalars(
                        sa.select(Permission).where(Permission.id.in_(payload.permission_ids))
                    )
                ).all()
                perm_map = {p.id: p for p in perms}
                missing = [pid for pid in payload.permission_ids if pid not in perm_map]
                if missing:
                    await session.rollback()
                    raise ValueError(f"Permissions not found: {', '.join(missing)}")
                for perm in perms:
                    session.add(RolePermissionBinding(role_id=role.id, permission_id=perm.id))

        await session.commit()
        return await self.get(session, role.id)

    async def delete(self, session: AsyncSession, role_id: str) -> "RoleDeleteResponse":
        from app.iam.schemas import RoleDeleteResponse

        role = await session.get(Role, role_id)
        if role is None:
            raise LookupError(f"Role '{role_id}' not found.")
        if role.is_system:
            raise ValueError(f"System role '{role.code}' cannot be deleted.")
        await session.delete(role)
        await session.commit()
        return RoleDeleteResponse(deleted=True, role_id=role_id)


class PermissionService:
    async def list(self, session: AsyncSession) -> list[PermissionRead]:
        stmt = sa.select(Permission).order_by(
            Permission.resource.asc(), Permission.action.asc()
        )
        permissions = (await session.scalars(stmt)).all()
        return [_serialize_permission(permission) for permission in permissions]

    async def get(self, session: AsyncSession, permission_id: str) -> PermissionRead:
        permission = await session.get(Permission, permission_id)
        if permission is None:
            raise LookupError(f"Permission '{permission_id}' not found.")
        return _serialize_permission(permission)

    async def create(
        self, session: AsyncSession, payload: "PermissionCreate"
    ) -> PermissionRead:
        from app.iam.schemas import PermissionCreate as _  # noqa: F401

        if payload.parent_id:
            parent = await session.get(Permission, payload.parent_id)
            if parent is None:
                raise LookupError(
                    f"Parent permission '{payload.parent_id}' not found."
                )

        permission = Permission(
            code=payload.code,
            resource=payload.resource,
            action=payload.action,
            type=payload.type,
            parent_id=payload.parent_id,
            description=payload.description,
        )
        session.add(permission)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError(
                f"Permission code '{payload.code}' already exists."
            ) from exc
        await session.refresh(permission)
        return _serialize_permission(permission)

    async def update(
        self,
        session: AsyncSession,
        permission_id: str,
        payload: "PermissionUpdate",
    ) -> PermissionRead:
        permission = await session.get(Permission, permission_id)
        if permission is None:
            raise LookupError(f"Permission '{permission_id}' not found.")

        if payload.code is not None:
            permission.code = payload.code
        if payload.resource is not None:
            permission.resource = payload.resource
        if payload.action is not None:
            permission.action = payload.action
        if payload.type is not None:
            permission.type = payload.type
        if payload.parent_id is not None:
            if payload.parent_id == "":
                permission.parent_id = None
            else:
                parent = await session.get(Permission, payload.parent_id)
                if parent is None:
                    raise LookupError(
                        f"Parent permission '{payload.parent_id}' not found."
                    )
                permission.parent_id = payload.parent_id
        if payload.description is not None:
            permission.description = payload.description

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError(
                f"Permission code '{payload.code}' already exists."
            ) from exc
        await session.refresh(permission)
        return _serialize_permission(permission)

    async def delete(
        self, session: AsyncSession, permission_id: str
    ) -> "PermissionDeleteResponse":
        from app.iam.schemas import PermissionDeleteResponse

        permission = await session.get(Permission, permission_id)
        if permission is None:
            raise LookupError(f"Permission '{permission_id}' not found.")

        binding_count = await session.scalar(
            sa.select(sa.func.count()).select_from(RolePermissionBinding).where(
                RolePermissionBinding.permission_id == permission_id
            )
        )
        if binding_count and binding_count > 0:
            raise ValueError(
                f"Permission '{permission.code}' is bound to {binding_count} role(s). "
                "Remove bindings before deleting."
            )

        await session.delete(permission)
        await session.commit()
        return PermissionDeleteResponse(deleted=True, permission_id=permission_id)


class UserService:
    async def list(self, session: AsyncSession) -> list[UserListItem]:
        stmt = (
            sa.select(UserAccount)
            .options(*USER_LOAD_OPTIONS)
            .order_by(UserAccount.created_at.asc())
        )
        users = (await session.scalars(stmt)).unique().all()
        return [serialize_user_list_item(user) for user in users]

    async def get(self, session: AsyncSession, user_id: str) -> UserRead:
        user = await self._load_user(session, user_id)
        if user is None:
            raise LookupError(f"User '{user_id}' not found.")
        return serialize_user(user)

    async def get_by_username(
        self, session: AsyncSession, username: str
    ) -> UserAccount | None:
        stmt = (
            sa.select(UserAccount)
            .where(UserAccount.username == username)
            .options(*USER_LOAD_OPTIONS)
        )
        return (await session.scalars(stmt)).unique().one_or_none()

    async def create(self, session: AsyncSession, payload: UserCreate) -> UserRead:
        roles = await self._resolve_roles(session, payload.role_ids)
        direct_permissions = await self._resolve_permissions(
            session, payload.direct_permissions
        )

        user = UserAccount(
            username=payload.username,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
            # 空串视为未填写，避免数据库里出现毫无意义的 ""
            phone=(payload.phone or None),
            department=(payload.department or None),
            status=payload.status,
            is_superuser=payload.is_superuser,
        )
        session.add(user)
        await session.flush()

        session.add_all(
            [UserRoleBinding(user_id=user.id, role_id=role.id) for role in roles],
        )
        session.add_all(
            [
                UserPermissionGrant(
                    user_id=user.id, permission_id=permission.id, effect=effect
                )
                for permission, effect in direct_permissions
            ],
        )

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError(f"Username '{payload.username}' already exists.") from exc
        refreshed = await self._load_user(session, user.id)
        if refreshed is None:
            raise LookupError(f"User '{user.id}' not found after creation.")
        return serialize_user(refreshed)

    async def update(
        self, session: AsyncSession, user_id: str, payload: UserUpdate
    ) -> UserRead:
        user = await self._load_user(session, user_id)
        if user is None:
            raise LookupError(f"User '{user_id}' not found.")

        roles: list[Role] | None = None
        if payload.role_ids is not None:
            roles = await self._resolve_roles(session, payload.role_ids)

        direct_permissions: list[tuple[Permission, PermissionEffect]] | None = None
        if payload.direct_permissions is not None:
            direct_permissions = await self._resolve_permissions(
                session, payload.direct_permissions
            )

        if payload.display_name is not None:
            user.display_name = payload.display_name
        if payload.password is not None:
            user.password_hash = hash_password(payload.password)
        # phone / department 沿用既有约定：传 None 不修改、传空串清除为 NULL、传非空串覆盖
        if payload.phone is not None:
            user.phone = payload.phone or None
        if payload.department is not None:
            user.department = payload.department or None
        if payload.status is not None:
            user.status = payload.status
        if payload.is_superuser is not None:
            user.is_superuser = payload.is_superuser
        if roles is not None:
            # 先清空再重建：SQLAlchemy cascade 会删除旧绑定记录
            user.role_bindings.clear()
            await session.flush()
            user.role_bindings.extend(
                UserRoleBinding(user_id=user.id, role_id=role.id) for role in roles
            )
        if direct_permissions is not None:
            user.direct_permission_grants.clear()
            await session.flush()
            user.direct_permission_grants.extend(
                UserPermissionGrant(
                    user_id=user.id, permission_id=permission.id, effect=effect
                )
                for permission, effect in direct_permissions
            )

        await session.commit()
        refreshed = await self._load_user(session, user.id)
        if refreshed is None:
            raise LookupError(f"User '{user.id}' not found after update.")
        return serialize_user(refreshed)

    async def mark_login_success(
        self, session: AsyncSession, user: UserAccount
    ) -> None:
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()

    async def delete(
        self, session: AsyncSession, user_id: str, acting_user_id: str | None = None
    ) -> UserDeleteResponse:
        user = await session.get(UserAccount, user_id)
        if user is None:
            raise LookupError(f"User '{user_id}' not found.")

        if acting_user_id and user.id == acting_user_id:
            raise ValueError("You cannot delete the current signed-in user.")

        if user.is_superuser:
            # 防止删除最后一个超级管理员导致系统无法管理
            remaining_superusers = await session.scalar(
                sa.select(sa.func.count())
                .select_from(UserAccount)
                .where(UserAccount.is_superuser.is_(True))
                .where(UserAccount.id != user.id),
            )
            if not remaining_superusers:
                raise ValueError("You cannot delete the last superuser.")

        await session.delete(user)
        await session.commit()
        return UserDeleteResponse(deleted=True, user_id=user_id)

    async def _load_user(
        self, session: AsyncSession, user_id: str
    ) -> UserAccount | None:
        stmt = (
            sa.select(UserAccount)
            .where(UserAccount.id == user_id)
            .options(*USER_LOAD_OPTIONS)
            # 确保 commit 后重新加载时获取最新数据，而不是从 Session 缓存中返回旧对象
            .execution_options(populate_existing=True)
        )
        return (await session.scalars(stmt)).unique().one_or_none()

    async def _resolve_roles(
        self, session: AsyncSession, role_ids: list[str]
    ) -> list[Role]:
        if not role_ids:
            return []
        stmt = sa.select(Role).where(Role.id.in_(role_ids))
        roles = (await session.scalars(stmt)).all()
        role_map = {role.id: role for role in roles}
        missing_ids = [role_id for role_id in role_ids if role_id not in role_map]
        if missing_ids:
            raise LookupError(f"Roles not found: {', '.join(missing_ids)}.")
        return [role_map[role_id] for role_id in role_ids]

    async def _resolve_permissions(
        self,
        session: AsyncSession,
        grants: list[UserPermissionGrantInput],
    ) -> list[tuple[Permission, PermissionEffect]]:
        if not grants:
            return []
        codes = [item.permission_code for item in grants]
        stmt = sa.select(Permission).where(Permission.code.in_(codes))
        permissions = (await session.scalars(stmt)).all()
        permission_map = {permission.code: permission for permission in permissions}
        missing_codes = [code for code in codes if code not in permission_map]
        if missing_codes:
            raise LookupError(f"Permissions not found: {', '.join(missing_codes)}.")
        return [(permission_map[item.permission_code], item.effect) for item in grants]
