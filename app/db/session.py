"""数据库引擎、Session 工厂及初始化逻辑。

SessionLocal 配置为 expire_on_commit=False，使提交后的对象在同一请求内
仍可直接访问属性，无需再次查询。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base


settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    future=True,
    # 连接池健康保障：从池中取连接前先探活，剔除被服务端/中间件单方面关闭的僵尸连接，
    # 同时定期回收，避免命中 PG 或中间代理的 idle 超时。
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    # 提交后不过期对象，避免在同一请求中访问关联属性时触发隐式懒加载
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入：为每个请求提供独立的异步 Session，请求结束后自动关闭。"""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """按需初始化数据库：建表并植入默认权限、角色和管理员账号。

    仅在 auto_create_tables=True 时由 lifespan 钩子调用，生产环境应通过 Alembic 管理表结构。
    """

    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    from app.iam.services.identity import IdentityBootstrapService

    async with SessionLocal() as session:
        await IdentityBootstrapService().ensure_defaults(session)
