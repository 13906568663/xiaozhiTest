from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.chatbot.services.chat_engine import ChatEngine
from app.chatbot.services.goal_judge import GoalJudge
from app.core.config import get_settings
from app.db.base import Base
from app.db.models import CapabilityRegistry
from app.domain.enums import BindingSource, CapabilityType
from app.schemas.common import CapabilityBinding
from app.workflow.runtime.node_runtime import NodeRuntime
from app.workflow.schemas import TaskNodeDefinition
from app.workflow.services.capability_resolver import CapabilityResolverService


PROVIDER_API_KEY = "provider-explicit-key"
GLOBAL_ENV_API_KEY = "env-global-key"


def _provider_model_config() -> dict[str, object]:
    return {
        "api_mode": "openai_compatible",
        "api_host": "https://provider.example/v1",
        "api_path": "/chat/completions",
        "api_key": PROVIDER_API_KEY,
        "model_name": "gpt-provider-test",
    }


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", GLOBAL_ENV_API_KEY)
    monkeypatch.setattr(settings, "openai_base_url", "https://env.example/v1")
    monkeypatch.setattr(settings, "default_model_name", "gpt-env-default")
    return settings


def test_chat_engine_prefers_provider_api_key_over_global_env(
    settings_override,
) -> None:
    engine = ChatEngine()

    provider = engine._build_provider(_provider_model_config())

    assert provider is not None
    assert provider.api_key == PROVIDER_API_KEY
    assert provider.api_key != settings_override.openai_api_key


def test_goal_judge_prefers_provider_api_key_over_global_env(
    settings_override,
) -> None:
    judge = GoalJudge()

    provider = judge._build_provider(_provider_model_config())

    assert provider is not None
    assert provider.api_key == PROVIDER_API_KEY
    assert provider.api_key != settings_override.openai_api_key


def test_node_runtime_prefers_provider_api_key_over_global_env(
    settings_override,
) -> None:
    runtime = NodeRuntime()
    node = TaskNodeDefinition(
        seq=1,
        code="model-node",
        name="Model Node",
        model=CapabilityBinding(
            source=BindingSource.NODE,
            config=_provider_model_config(),
        ),
    )

    provider = runtime._build_provider(node)

    assert provider is not None
    assert provider.api_key == PROVIDER_API_KEY
    assert provider.api_key != settings_override.openai_api_key


def test_deepseek_compatible_mode_uses_provider_api_key(
    settings_override,
) -> None:
    config = {
        **_provider_model_config(),
        "api_mode": "deepseek_compatible",
        "model_name": "deepseek-chat",
    }

    chat_provider = ChatEngine()._build_provider(config)
    judge_provider = GoalJudge()._build_provider(config)
    runtime_provider = NodeRuntime()._build_provider(
        TaskNodeDefinition(
            seq=1,
            code="deepseek-node",
            name="DeepSeek Node",
            model=CapabilityBinding(
                source=BindingSource.NODE,
                config=config,
            ),
        )
    )

    assert chat_provider is not None
    assert judge_provider is not None
    assert runtime_provider is not None
    assert chat_provider.api_key == PROVIDER_API_KEY
    assert judge_provider.api_key == PROVIDER_API_KEY
    assert runtime_provider.api_key == PROVIDER_API_KEY


@pytest.mark.asyncio
async def test_capability_resolver_keeps_provider_api_key_when_overriding_model_name(
    settings_override,
) -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    await prepare_database()

    async with session_factory() as session:
        await _seed_provider_capability(session)

        resolved = await CapabilityResolverService().resolve_binding(
            session,
            CapabilityBinding(
                source=BindingSource.GLOBAL,
                ref="provider_with_key",
                config={"model_name": "gpt-node-override"},
            ),
            CapabilityType.MODEL,
        )

        assert resolved is not None
        assert resolved.config["api_key"] == PROVIDER_API_KEY
        assert resolved.config["model_name"] == "gpt-node-override"
        assert resolved.config["api_key"] != settings_override.openai_api_key

    await engine.dispose()


async def _seed_provider_capability(session: AsyncSession) -> None:
    capability = CapabilityRegistry(
        type=CapabilityType.MODEL,
        code="provider_with_key",
        name="Provider With Key",
        description="Regression test provider",
        status="active",
        config_json=_provider_model_config(),
    )
    session.add(capability)
    await session.commit()
