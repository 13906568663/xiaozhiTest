from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter()


@router.get("/healthz")
async def healthcheck() -> dict[str, str | bool]:
    """服务健康检查端点，返回运行态基础信息。"""
    settings = get_settings()
    return {
        "status": "ok",
        "app_name": settings.app_name,
    }
