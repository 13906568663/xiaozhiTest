"""
ORM 模型包 — 按业务域拆分：
  - capability.py : 能力注册（模型 / MCP）
  - chatbot.py    : 聊天机器人、会话、消息、工具调用日志
  - iam.py        : 用户、角色、权限及 API Key
  - knowledge.py  : 知识库、文档、分块向量
  - memory.py     : 用户记忆存储
  - skill.py      : 技能（SKILL.md 文档）
  - workflow.py   : 节点运行记录与 artifact（对话引擎底座）

从外部统一通过 `from app.db.models import Xxx` 引用。
Alembic env.py 只需 `import app.db.models` 即可发现全部表。
"""

from app.db.models.capability import CapabilityRegistry
from app.db.models.chatbot import (
    Chatbot,
    ChatMessage,
    ChatSession,
    ToolCallLog,
)
from app.db.models.iam import (
    Permission,
    Role,
    RolePermissionBinding,
    UserAccount,
    UserApiKey,
    UserPermissionGrant,
    UserRoleBinding,
)
from app.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.db.models.memory import MemoryStore
from app.db.models.skill import Skill
from app.db.models.workflow import (
    NodeRun,
    NodeRunArtifact,
    TaskNode,
    TaskRun,
    TaskTemplate,
    TaskTemplateVersion,
)

__all__ = [
    "CapabilityRegistry",
    "Chatbot",
    "ChatMessage",
    "ChatSession",
    "KnowledgeBase",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "MemoryStore",
    "NodeRun",
    "NodeRunArtifact",
    "Permission",
    "Role",
    "RolePermissionBinding",
    "Skill",
    "TaskNode",
    "TaskRun",
    "TaskTemplate",
    "TaskTemplateVersion",
    "ToolCallLog",
    "UserAccount",
    "UserApiKey",
    "UserPermissionGrant",
    "UserRoleBinding",
]
