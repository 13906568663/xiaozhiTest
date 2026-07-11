"""权限与角色的静态定义，是系统 RBAC 数据的唯一权威来源。

IdentityBootstrapService 在首次启动时读取此模块的常量，
将权限、角色和角色-权限绑定写入数据库。
新增权限或调整角色权限集时，只需修改本文件，无需编写数据迁移脚本。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import PermissionType


@dataclass(frozen=True)
class PermissionDefinition:
    """描述一条权限的静态定义，不含 ID，与数据库行解耦。"""

    code: str
    resource: str
    action: str
    description: str
    type: PermissionType = field(default=PermissionType.API)


@dataclass(frozen=True)
class RoleDefinition:
    """描述一个角色的静态定义。is_system=True 表示系统保留角色，不允许删除。"""

    code: str
    name: str
    description: str
    is_system: bool = True


class PermissionCode:
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    ROLES_READ = "roles:read"
    ROLES_CREATE = "roles:create"
    ROLES_UPDATE = "roles:update"
    ROLES_DELETE = "roles:delete"
    PERMISSIONS_READ = "permissions:read"
    PERMISSIONS_CREATE = "permissions:create"
    PERMISSIONS_UPDATE = "permissions:update"
    PERMISSIONS_DELETE = "permissions:delete"

    CAPABILITIES_READ = "capabilities:read"
    CAPABILITIES_CREATE = "capabilities:create"
    CAPABILITIES_UPDATE = "capabilities:update"
    CAPABILITIES_DELETE = "capabilities:delete"

    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"

    CHATBOTS_READ = "chatbots:read"
    CHATBOTS_WRITE = "chatbots:write"
    CHATBOTS_MANAGE = "chatbots:manage"

    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"

    TOOLSETS_READ = "toolsets:read"
    TOOLSETS_WRITE = "toolsets:write"

    SKILLS_READ = "skills:read"
    SKILLS_WRITE = "skills:write"


class RoleCode:
    PLATFORM_ADMIN = "platform_admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


DEFAULT_PERMISSION_DEFINITIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition(
        code=PermissionCode.USERS_READ,
        resource="users",
        action="read",
        description="View users, their assigned roles, and effective permissions.",
    ),
    PermissionDefinition(
        code=PermissionCode.USERS_CREATE,
        resource="users",
        action="create",
        description="Create new user accounts.",
    ),
    PermissionDefinition(
        code=PermissionCode.USERS_UPDATE,
        resource="users",
        action="update",
        description="Update user profiles, passwords, roles, and direct permission grants.",
    ),
    PermissionDefinition(
        code=PermissionCode.USERS_DELETE,
        resource="users",
        action="delete",
        description="Delete user accounts.",
    ),
    PermissionDefinition(
        code=PermissionCode.ROLES_READ,
        resource="roles",
        action="read",
        description="View role definitions and bundled permissions.",
    ),
    PermissionDefinition(
        code=PermissionCode.ROLES_CREATE,
        resource="roles",
        action="create",
        description="Create new roles and assign initial permissions.",
    ),
    PermissionDefinition(
        code=PermissionCode.ROLES_UPDATE,
        resource="roles",
        action="update",
        description="Update role metadata and replace role permission bindings.",
    ),
    PermissionDefinition(
        code=PermissionCode.ROLES_DELETE,
        resource="roles",
        action="delete",
        description="Delete non-system roles.",
    ),
    PermissionDefinition(
        code=PermissionCode.PERMISSIONS_READ,
        resource="permissions",
        action="read",
        description="View the permission catalog.",
    ),
    PermissionDefinition(
        code=PermissionCode.PERMISSIONS_CREATE,
        resource="permissions",
        action="create",
        description="Create new permission entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.PERMISSIONS_UPDATE,
        resource="permissions",
        action="update",
        description="Update permission entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.PERMISSIONS_DELETE,
        resource="permissions",
        action="delete",
        description="Delete permission entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.CAPABILITIES_READ,
        resource="capabilities",
        action="read",
        description="View capability registry entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.CAPABILITIES_CREATE,
        resource="capabilities",
        action="create",
        description="Create capability registry entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.CAPABILITIES_UPDATE,
        resource="capabilities",
        action="update",
        description="Update capability registry entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.CAPABILITIES_DELETE,
        resource="capabilities",
        action="delete",
        description="Delete capability registry entries.",
    ),
    PermissionDefinition(
        code=PermissionCode.KNOWLEDGE_READ,
        resource="knowledge",
        action="read",
        description="View knowledge bases, documents, and search results.",
    ),
    PermissionDefinition(
        code=PermissionCode.KNOWLEDGE_WRITE,
        resource="knowledge",
        action="write",
        description="Create, update, delete knowledge bases and documents.",
    ),
    PermissionDefinition(
        code=PermissionCode.CHATBOTS_READ,
        resource="chatbots",
        action="read",
        description="View chatbot configurations and chat sessions.",
    ),
    PermissionDefinition(
        code=PermissionCode.CHATBOTS_WRITE,
        resource="chatbots",
        action="write",
        description="Create, update, delete chatbots and manage chat sessions.",
    ),
    PermissionDefinition(
        code=PermissionCode.CHATBOTS_MANAGE,
        resource="chatbots",
        action="manage",
        description="Full chatbot administration.",
    ),
    PermissionDefinition(
        code=PermissionCode.MEMORY_READ,
        resource="memory",
        action="read",
        description="View stored user memories.",
    ),
    PermissionDefinition(
        code=PermissionCode.MEMORY_WRITE,
        resource="memory",
        action="write",
        description="Delete or clear user memories.",
    ),
    PermissionDefinition(
        code=PermissionCode.TOOLSETS_READ,
        resource="toolsets",
        action="read",
        description="View dynamic HTTP tool definitions.",
    ),
    PermissionDefinition(
        code=PermissionCode.TOOLSETS_WRITE,
        resource="toolsets",
        action="write",
        description="Create, update, and delete dynamic HTTP tools.",
    ),
    PermissionDefinition(
        code=PermissionCode.SKILLS_READ,
        resource="skills",
        action="read",
        description="View SKILL.md documents available to chatbots.",
    ),
    PermissionDefinition(
        code=PermissionCode.SKILLS_WRITE,
        resource="skills",
        action="write",
        description="Create, update, and delete SKILL.md documents.",
    ),
)


DEFAULT_ROLE_DEFINITIONS: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        code=RoleCode.PLATFORM_ADMIN,
        name="Platform Admin",
        description="Full access to users, permissions, capabilities, and platform configuration.",
    ),
    RoleDefinition(
        code=RoleCode.OPERATOR,
        name="Operator",
        description="Manage platform capabilities and configuration without IAM administration.",
    ),
    RoleDefinition(
        code=RoleCode.VIEWER,
        name="Viewer",
        description="Read-only access to platform configuration.",
    ),
)


DEFAULT_ROLE_PERMISSION_CODES: dict[str, tuple[str, ...]] = {
    RoleCode.PLATFORM_ADMIN: tuple(
        permission.code for permission in DEFAULT_PERMISSION_DEFINITIONS
    ),
    RoleCode.OPERATOR: (
        PermissionCode.ROLES_READ,
        PermissionCode.ROLES_CREATE,
        PermissionCode.ROLES_UPDATE,
        PermissionCode.ROLES_DELETE,
        PermissionCode.PERMISSIONS_READ,
        PermissionCode.PERMISSIONS_CREATE,
        PermissionCode.PERMISSIONS_UPDATE,
        PermissionCode.PERMISSIONS_DELETE,
        PermissionCode.CAPABILITIES_READ,
        PermissionCode.CAPABILITIES_CREATE,
        PermissionCode.CAPABILITIES_UPDATE,
        PermissionCode.CAPABILITIES_DELETE,
        PermissionCode.KNOWLEDGE_READ,
        PermissionCode.KNOWLEDGE_WRITE,
        PermissionCode.CHATBOTS_READ,
        PermissionCode.CHATBOTS_WRITE,
        PermissionCode.MEMORY_READ,
        PermissionCode.MEMORY_WRITE,
        PermissionCode.TOOLSETS_READ,
        PermissionCode.TOOLSETS_WRITE,
        PermissionCode.SKILLS_READ,
        PermissionCode.SKILLS_WRITE,
    ),
    RoleCode.VIEWER: (
        PermissionCode.ROLES_READ,
        PermissionCode.PERMISSIONS_READ,
        PermissionCode.CAPABILITIES_READ,
        PermissionCode.KNOWLEDGE_READ,
        PermissionCode.CHATBOTS_READ,
        PermissionCode.MEMORY_READ,
        PermissionCode.TOOLSETS_READ,
        PermissionCode.SKILLS_READ,
    ),
}
