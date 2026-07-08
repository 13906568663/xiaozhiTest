"""IAM 域 ORM 模型。

包含权限、角色、用户账号及其关联关系的表定义。
权限模型采用"RBAC + 用户直接授权"双轨机制：
  - 角色权限：通过 Role -> RolePermissionBinding -> Permission 关联
  - 直接授权：通过 UserPermissionGrant 对单个用户追加或拒绝特定权限
有效权限在服务层计算（角色权限 ∪ 直接允许 − 直接拒绝）。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import PermissionEffect, PermissionType, RoleStatus, UserStatus


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """权限原子定义，由 code（如 "users:read"）唯一标识。"""

    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    resource: Mapped[str] = mapped_column(sa.String(64), index=True)
    action: Mapped[str] = mapped_column(sa.String(64), index=True)
    type: Mapped[PermissionType] = mapped_column(
        sa.Enum(PermissionType, native_enum=False),
        default=PermissionType.API,
        nullable=False,
        server_default="API",
    )
    parent_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("permission.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    role_bindings: Mapped[list["RolePermissionBinding"]] = relationship(
        back_populates="permission",
        cascade="all, delete-orphan",
    )
    user_grants: Mapped[list["UserPermissionGrant"]] = relationship(
        back_populates="permission",
        cascade="all, delete-orphan",
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """角色定义，将一组权限打包赋予用户。

    is_system=True 的角色由系统引导创建，不应被删除或重命名。
    """

    __tablename__ = "role"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # 使用字符串枚举而非数据库原生枚举，以便在不修改表结构的情况下新增枚举值
    status: Mapped[RoleStatus] = mapped_column(
        sa.Enum(RoleStatus, native_enum=False),
        default=RoleStatus.ACTIVE,
        nullable=False,
    )
    is_system: Mapped[bool] = mapped_column(sa.Boolean(), default=False, nullable=False)

    permission_bindings: Mapped[list["RolePermissionBinding"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )
    user_bindings: Mapped[list["UserRoleBinding"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """用户账号，存储认证凭据和授权关系。

    is_superuser=True 的用户绕过所有权限校验，等同于超级管理员。
    密码以 PBKDF2-SHA256 哈希存储，明文密码不落盘。
    """

    __tablename__ = "user_account"

    username: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(sa.String(255))
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    # 联系方式与组织归属，仅作展示/检索使用，不参与认证逻辑，因此允许为空。
    phone: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    department: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        sa.Enum(UserStatus, native_enum=False),
        default=UserStatus.ACTIVE,
        nullable=False,
    )
    is_superuser: Mapped[bool] = mapped_column(
        sa.Boolean(), default=False, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    role_bindings: Mapped[list["UserRoleBinding"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    direct_permission_grants: Mapped[list["UserPermissionGrant"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    api_keys: Mapped[list["UserApiKey"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class RolePermissionBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """角色与权限的多对多关联表。"""

    __tablename__ = "role_permission_binding"
    __table_args__ = (
        sa.UniqueConstraint(
            "role_id", "permission_id", name="uq_role_permission_binding"
        ),
    )

    role_id: Mapped[str] = mapped_column(
        sa.ForeignKey("role.id", ondelete="CASCADE"),
        index=True,
    )
    permission_id: Mapped[str] = mapped_column(
        sa.ForeignKey("permission.id", ondelete="CASCADE"),
        index=True,
    )

    role: Mapped[Role] = relationship(back_populates="permission_bindings")
    permission: Mapped[Permission] = relationship(back_populates="role_bindings")


class UserRoleBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """用户与角色的多对多关联表。"""

    __tablename__ = "user_role_binding"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role_binding"),
    )

    user_id: Mapped[str] = mapped_column(
        sa.ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
    )
    role_id: Mapped[str] = mapped_column(
        sa.ForeignKey("role.id", ondelete="CASCADE"),
        index=True,
    )

    user: Mapped[UserAccount] = relationship(back_populates="role_bindings")
    role: Mapped[Role] = relationship(back_populates="user_bindings")


class UserPermissionGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """用户直接权限授予记录，支持 ALLOW / DENY 双向效果。

    DENY 效果可用于从角色继承的权限中精确撤销某一条，
    实现细粒度的权限覆盖而不必修改角色定义。
    """

    __tablename__ = "user_permission_grant"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "permission_id", name="uq_user_permission_grant"
        ),
    )

    user_id: Mapped[str] = mapped_column(
        sa.ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
    )
    permission_id: Mapped[str] = mapped_column(
        sa.ForeignKey("permission.id", ondelete="CASCADE"),
        index=True,
    )
    effect: Mapped[PermissionEffect] = mapped_column(
        sa.Enum(PermissionEffect, native_enum=False),
        default=PermissionEffect.ALLOW,
        nullable=False,
    )

    user: Mapped[UserAccount] = relationship(back_populates="direct_permission_grants")
    permission: Mapped[Permission] = relationship(back_populates="user_grants")


class UserApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """用户 API Key 记录。

    仅存储密钥的哈希值（secret_hash），原始密钥仅在创建时返回一次，
    系统不持久化明文，无法再次查看。
    key_prefix 作为快速查找索引，格式为 "agk_<hex>"，对用户可见且安全。
    """

    __tablename__ = "user_api_key"

    user_id: Mapped[str] = mapped_column(
        sa.ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    # revoked_at 非空表示该密钥已被吊销，即使未到期也不可使用
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped[UserAccount] = relationship(back_populates="api_keys")
