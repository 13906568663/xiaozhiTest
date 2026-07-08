"""IAM 域 Pydantic Schema — 合并 auth / identity / profile 三类 schema。

所有响应 Schema 均使用 model_validate（ORM Mode）从 SQLAlchemy 模型实例构建，
因此字段名须与 ORM 模型属性名保持一致。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import PermissionEffect, PermissionType, RoleStatus, UserStatus
from app.schemas.common import TimestampsMixin


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------


class AuthLoginRequest(BaseModel):
    """用户登录请求。"""

    username: str = Field(description="登录用户名")
    password: str = Field(description="登录密码")


class AuthLoginResponse(BaseModel):
    """登录成功的响应，包含 JWT Token 和用户信息。"""

    access_token: str = Field(description="JWT 访问令牌，后续请求通过 Bearer Token 或 Cookie 携带")
    token_type: str = Field(default="bearer", description="令牌类型，固定为 bearer")
    # UserRead 在此处仍为前向引用，文件末尾调用 model_rebuild() 解析
    user: "UserRead" = Field(description="当前登录用户的完整信息")


class AuthLogoutResponse(BaseModel):
    """登出响应。"""

    success: bool = Field(default=True, description="是否登出成功")


# ---------------------------------------------------------------------------
# Identity schemas
# ---------------------------------------------------------------------------


class PermissionRead(TimestampsMixin):
    """权限条目的读取响应。"""

    code: str = Field(description="权限码，格式为 'resource:action'（如 'users:read'）")
    resource: str = Field(description="资源名称（如 users、templates、runs）")
    action: str = Field(description="操作类型（如 read、create、update、delete）")
    type: PermissionType = Field(description="权限类型：menu 菜单 / button 按钮 / api 接口")
    parent_id: str | None = Field(default=None, description="所属上级权限 ID（用于菜单/按钮与菜单的从属关系）")
    description: str | None = Field(default=None, description="权限用途说明")


class PermissionCreate(BaseModel):
    """创建权限请求。"""

    code: str = Field(min_length=1, max_length=128, description="权限码，格式为 'resource:action'")
    resource: str = Field(min_length=1, max_length=64, description="资源名称")
    action: str = Field(min_length=1, max_length=64, description="操作类型")
    type: PermissionType = Field(default=PermissionType.API, description="权限类型：menu / button / api")
    parent_id: str | None = Field(default=None, description="所属上级权限 ID")
    description: str | None = Field(default=None, description="权限用途说明")


class PermissionUpdate(BaseModel):
    """更新权限请求，所有字段可选。"""

    code: str | None = Field(default=None, min_length=1, max_length=128, description="权限码")
    resource: str | None = Field(default=None, min_length=1, max_length=64, description="资源名称")
    action: str | None = Field(default=None, min_length=1, max_length=64, description="操作类型")
    type: PermissionType | None = Field(default=None, description="权限类型")
    parent_id: str | None = Field(default=None, description="所属上级权限 ID，传空字符串清除")
    description: str | None = Field(default=None, description="权限用途说明")


class PermissionDeleteResponse(BaseModel):
    """权限删除响应。"""

    deleted: bool = Field(description="是否删除成功")
    permission_id: str = Field(description="被删除的权限 ID")


class RoleSummaryRead(TimestampsMixin):
    """角色的精简读取响应（不含权限列表），用于用户列表等嵌套场景。"""

    code: str = Field(description="角色唯一编码（如 platform_admin、operator、viewer）")
    name: str = Field(description="角色显示名称")
    description: str | None = Field(default=None, description="角色职责说明")
    status: RoleStatus = Field(description="角色状态：ACTIVE 启用 / DISABLED 停用")
    is_system: bool = Field(description="是否为系统内置角色（内置角色不可删除）")


class RoleRead(RoleSummaryRead):
    """角色的完整读取响应，包含该角色拥有的所有权限。"""

    permissions: list[PermissionRead] = Field(default_factory=list, description="角色关联的权限列表")


class UserPermissionGrantInput(BaseModel):
    """用户直接权限授予的输入。"""

    permission_code: str = Field(description="要授予/拒绝的权限码")
    effect: PermissionEffect = Field(default=PermissionEffect.ALLOW, description="授权效果：ALLOW 允许 / DENY 拒绝（DENY 优先于角色权限）")


class UserPermissionGrantRead(BaseModel):
    """用户直接权限授予的读取响应。"""

    effect: PermissionEffect = Field(description="授权效果")
    permission: PermissionRead = Field(description="关联的权限详情")


class UserListItem(TimestampsMixin):
    """用户列表的精简响应。"""

    username: str = Field(description="登录用户名，全局唯一")
    display_name: str = Field(description="用户显示名称")
    phone: str | None = Field(default=None, description="联系电话，可为空")
    department: str | None = Field(default=None, description="所属部门，可为空")
    status: UserStatus = Field(description="用户状态：ACTIVE 正常 / DISABLED 已禁用")
    is_superuser: bool = Field(description="是否为超级管理员（跳过所有权限检查）")
    last_login_at: datetime | None = Field(default=None, description="最后登录时间")
    roles: list[RoleSummaryRead] = Field(default_factory=list, description="用户关联的角色列表")


class UserRead(UserListItem):
    """完整用户信息，包含直接授权和最终有效权限列表。

    permissions 是服务层计算后的有效权限合集（角色权限 ∪ 直接允许 − 直接拒绝），
    供 require_permission 依赖直接查找，避免重复计算。
    """

    direct_permissions: list[UserPermissionGrantRead] = Field(default_factory=list, description="用户的直接权限授予记录（绕过角色直接赋权/拒权）")
    permissions: list[PermissionRead] = Field(default_factory=list, description="用户最终生效的权限合集（角色权限 ∪ 直接允许 − 直接拒绝）")


class UserDeleteResponse(BaseModel):
    """用户删除的响应。"""

    deleted: bool = Field(description="是否删除成功")
    user_id: str = Field(description="被删除的用户 ID")


class UserCreate(BaseModel):
    """创建用户的请求体。"""

    username: str = Field(min_length=3, max_length=128, description="登录用户名，3-128 字符，全局唯一")
    display_name: str = Field(min_length=1, max_length=255, description="用户显示名称")
    password: str = Field(min_length=8, max_length=255, description="登录密码，至少 8 位")
    phone: str | None = Field(default=None, max_length=32, description="联系电话，可为空")
    department: str | None = Field(default=None, max_length=128, description="所属部门，可为空")
    status: UserStatus = Field(default=UserStatus.ACTIVE, description="初始用户状态")
    is_superuser: bool = Field(default=False, description="是否设为超级管理员")
    role_ids: list[str] = Field(default_factory=list, description="要关联的角色 ID 列表")
    direct_permissions: list[UserPermissionGrantInput] = Field(default_factory=list, description="直接权限授予列表")

    @model_validator(mode="after")
    def validate_uniques(self) -> "UserCreate":
        # 数据库层有唯一约束，但在应用层提前校验可提供更友好的错误信息
        if len(self.role_ids) != len(set(self.role_ids)):
            raise ValueError("role_ids must be unique")
        codes = [item.permission_code for item in self.direct_permissions]
        if len(codes) != len(set(codes)):
            raise ValueError("direct permission codes must be unique")
        return self


class UserUpdate(BaseModel):
    """用户更新请求，所有字段均为可选，仅修改提供的字段。

    role_ids / direct_permissions 为全量替换语义：
    传空列表会清除所有角色/直接权限，传 None 则不做任何修改。
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=255, description="新的显示名称，传 None 不修改")
    password: str | None = Field(default=None, min_length=8, max_length=255, description="新密码，传 None 不修改")
    phone: str | None = Field(default=None, max_length=32, description="联系电话：传 None 不修改、传空串清除、传非空串覆盖")
    department: str | None = Field(default=None, max_length=128, description="所属部门：传 None 不修改、传空串清除、传非空串覆盖")
    status: UserStatus | None = Field(default=None, description="新的用户状态，传 None 不修改")
    is_superuser: bool | None = Field(default=None, description="是否设为超级管理员，传 None 不修改")
    role_ids: list[str] | None = Field(default=None, description="全量替换角色：传列表替换、传空列表清除、传 None 不修改")
    direct_permissions: list[UserPermissionGrantInput] | None = Field(default=None, description="全量替换直接权限：传列表替换、传空列表清除、传 None 不修改")

    @model_validator(mode="after")
    def validate_uniques(self) -> "UserUpdate":
        if self.role_ids is not None and len(self.role_ids) != len(set(self.role_ids)):
            raise ValueError("role_ids must be unique")
        if self.direct_permissions is not None:
            codes = [item.permission_code for item in self.direct_permissions]
            if len(codes) != len(set(codes)):
                raise ValueError("direct permission codes must be unique")
        return self


# ---------------------------------------------------------------------------
# Profile schemas
# ---------------------------------------------------------------------------


class ApiKeyRead(TimestampsMixin):
    """API Key 的读取响应（不含明文密钥）。"""

    name: str = Field(description="API Key 的备注名称（如 'CI/CD Pipeline'）")
    key_prefix: str = Field(description="密钥前缀（如 'sk-abc1****'），用于辨识而不暴露完整密钥")
    last_used_at: datetime | None = Field(default=None, description="最后使用时间")
    expires_at: datetime | None = Field(default=None, description="过期时间，为空表示永不过期")
    revoked_at: datetime | None = Field(default=None, description="吊销时间，非空表示已手动吊销")
    is_active: bool = Field(description="是否有效（由服务层根据过期和吊销状态计算）")


class ApiKeyCreateRequest(BaseModel):
    """创建 API Key 的请求体。"""

    name: str = Field(min_length=1, max_length=255, description="API Key 备注名称")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class ApiKeyCreateResponse(BaseModel):
    """创建 API Key 的响应，包含明文密钥（仅此一次）。"""

    api_key: ApiKeyRead = Field(description="创建的 API Key 元信息")
    plain_text_key: str = Field(description="完整的 API Key 明文，仅创建时返回一次，系统不持久化明文")


class ProfileRead(BaseModel):
    """当前登录用户的个人中心响应。"""

    user: UserRead = Field(description="当前用户的完整信息")
    api_keys: list[ApiKeyRead] = Field(default_factory=list, description="当前用户的所有 API Key")


class PasswordChangeRequest(BaseModel):
    """修改密码请求。"""

    current_password: str = Field(description="当前密码")
    new_password: str = Field(min_length=8, max_length=255, description="新密码")


class RoleCreate(BaseModel):
    """创建角色请求。"""

    code: str = Field(min_length=1, max_length=64, description="角色唯一编码")
    name: str = Field(min_length=1, max_length=128, description="角色显示名称")
    description: str | None = Field(default=None, description="角色职责说明")
    permission_ids: list[str] = Field(default_factory=list, description="关联的权限 ID 列表")


class RoleUpdate(BaseModel):
    """更新角色请求，所有字段可选。"""

    name: str | None = Field(default=None, min_length=1, max_length=128, description="角色显示名称")
    description: str | None = Field(default=None, description="角色职责说明")
    status: RoleStatus | None = Field(default=None, description="角色状态")
    permission_ids: list[str] | None = Field(
        default=None,
        description="全量替换权限：传列表替换、传空列表清除、传 None 不修改",
    )


class RoleDeleteResponse(BaseModel):
    """角色删除响应。"""

    deleted: bool = Field(description="是否删除成功")
    role_id: str = Field(description="被删除的角色 ID")


# AuthLoginResponse 中引用了前向声明的 UserRead，需在所有类定义完成后重建模型
AuthLoginResponse.model_rebuild()
