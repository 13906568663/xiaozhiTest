from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import CapabilityRegistry
from app.domain.enums import CapabilityType
from app.knowledge.services import knowledge_base as kb_service


PROVIDER_CODE = "embedding_provider"
PROVIDER_CONFIG = {
    "api_mode": "openai_compatible",
    "api_host": "https://provider.example/v1",
    "api_path": "/chat/completions",
    "api_key": "provider-secret-key",
    "api_key_env": "PROVIDER_API_KEY",
    "model_name": "gpt-provider-default",
}


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_normalize_embedding_config_rejects_missing_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="Provider 'missing_provider' 不存在"):
            await kb_service.normalize_embedding_config(
                session,
                {"provider_ref": "missing_provider"},
            )


@pytest.mark.asyncio
async def test_normalize_embedding_config_keeps_provider_binding_minimal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_provider_capability(session)

        normalized = await kb_service.normalize_embedding_config(
            session,
            {
                "provider_ref": PROVIDER_CODE,
                "api_host": "https://should-be-ignored.example/v1",
                "api_key": "should-be-ignored",
                "api_key_env": "SHOULD_BE_IGNORED",
                "api_path": "custom-embeddings",
            },
        )

        assert normalized == {
            "provider_ref": PROVIDER_CODE,
            "api_path": "/custom-embeddings",
        }


@pytest.mark.asyncio
async def test_resolve_embedding_config_reuses_provider_credentials(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_provider_capability(session)

        resolved = await kb_service.resolve_embedding_config(
            session,
            {
                "provider_ref": PROVIDER_CODE,
                "api_path": "/embeddings",
            },
        )

        assert resolved["provider_ref"] == PROVIDER_CODE
        assert resolved["api_host"] == PROVIDER_CONFIG["api_host"]
        assert resolved["api_key"] == PROVIDER_CONFIG["api_key"]
        assert resolved["api_key_env"] == PROVIDER_CONFIG["api_key_env"]
        assert resolved["api_path"] == "/embeddings"
        assert resolved["api_path"] != PROVIDER_CONFIG["api_path"]


async def _seed_provider_capability(session: AsyncSession) -> None:
    session.add(
        CapabilityRegistry(
            type=CapabilityType.MODEL,
            code=PROVIDER_CODE,
            name="Embedding Provider",
            description="Provider used by knowledge base tests",
            status="active",
            config_json=PROVIDER_CONFIG,
        )
    )
    await session.commit()
