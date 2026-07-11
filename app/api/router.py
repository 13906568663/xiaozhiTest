"""API 路由聚合器，将各域路由挂载到统一的 api_router。

认证策略：
  - /auth：公开端点（无需鉴权）
  - /chat/public：公开端点（通过 access_token 鉴权）
  - 其余所有路由：通过 dependencies=[Depends(require_current_user)] 统一要求认证
    细粒度权限校验由各路由端点内部通过 require_permission() 声明

新增域路由时，在此文件 include_router 并指定合适的 prefix 和 tags 即可。
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_current_user
from app.api.routes import health
from app.capabilities.routes import capabilities
from app.chatbot.routes import chat, chatbots, public_chat, session_admin
from app.iam.routes import auth, permissions, profile, roles, users
from app.knowledge.routes import knowledge_bases
from app.memory.routes import memories as memory_routes
from app.skill.routes import skills as skills_routes
from app.toolset.routes import toolsets


api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])

api_router.include_router(
    profile.router,
    prefix="/profile",
    tags=["profile"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    capabilities.router,
    prefix="/capabilities",
    tags=["capabilities"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    roles.router,
    prefix="/roles",
    tags=["roles"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    permissions.router,
    prefix="/permissions",
    tags=["permissions"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    knowledge_bases.router,
    prefix="/knowledge-bases",
    tags=["knowledge"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    memory_routes.router,
    prefix="/memories",
    tags=["memories"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    toolsets.router,
    prefix="/toolsets",
    tags=["toolsets"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    skills_routes.router,
    prefix="/skills",
    tags=["skills"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    chatbots.router,
    prefix="/chatbots",
    tags=["chatbots"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_current_user)],
)
api_router.include_router(
    session_admin.router,
    prefix="/admin/sessions",
    tags=["admin-sessions"],
    dependencies=[Depends(require_current_user)],
)
# 公开聊天端点供临时机器人使用，通过 access_token 鉴权，不要求用户认证
api_router.include_router(
    public_chat.router, prefix="/chat/public", tags=["public-chat"]
)
