from __future__ import annotations

import asyncio
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.chatbot.services.chat_engine import ChatEngine
from app.db.base import Base
from app.db.models import CapabilityRegistry, DynamicTool
from app.db.models.chatbot import Chatbot
from app.domain.enums import (
    CapabilityType,
    ChatbotType,
    CompensationActionType,
    CompensationTrigger,
)
from app.schemas.common import CapabilityBinding, CompensationAction, CompensationRule
from app.runtime_core.tool_protocol import ToolRegistry, ToolResult
from app.workflow.runtime import tool_registry as tr
from app.workflow.runtime.mcp_invoker import build_mcp_client, resolve_mcp_tool_name
from app.workflow.schemas import TaskNodeDefinition
from app.workflow.services.capability_resolver import CapabilityResolverService


def test_chat_engine_resolves_global_mcp_binding_before_registering_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        db_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        chat_engine = ChatEngine()

        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            session.add(
                CapabilityRegistry(
                    type=CapabilityType.MODEL,
                    code="openai_prod",
                    name="OpenAI Prod",
                    status="active",
                    config_json={
                        "api_mode": "openai_compatible",
                        "api_key": "test-key",
                        "api_host": "https://api.example.com/v1",
                        "model_name": "gpt-5.2",
                    },
                )
            )
            session.add(
                CapabilityRegistry(
                    type=CapabilityType.MCP,
                    code="mock_mcp",
                    name="Mock MCP",
                    status="active",
                    config_json={
                        "client_type": "http_stateless",
                        "transport": "streamable_http",
                        "url": "http://127.0.0.1:18080/mcp",
                        "timeout_seconds": 45,
                    },
                )
            )
            await session.commit()

            bot = Chatbot(
                id="bot-test-001",
                name="Ops Bot",
                description=None,
                type=ChatbotType.NORMAL,
                system_prompt="Use tools when needed.",
                goal_prompt="",
                model_binding={"source": "global", "ref": "openai_prod", "config": {}},
                mcp_bindings=[{"source": "global", "ref": "mock_mcp", "config": {}}],
                function_bindings=[],
                knowledge_bindings=[],
                max_turns=5,
                created_by=None,
            )
            resolved_node = await chat_engine._resolve_node(session, bot)
            captured: dict[str, object] = {}

            async def fake_register_mcps(
                toolkit: object,
                node: object,
                *,
                db_session: object | None = None,
            ) -> tuple[list[object], dict[str, str]]:
                captured["node"] = node
                captured["db_session"] = db_session
                return [], {}

            from app.workflow.runtime import tool_registry

            monkeypatch.setattr(tool_registry, "register_mcps", fake_register_mcps)
            monkeypatch.setattr(
                tool_registry,
                "register_functions",
                lambda toolkit, node, context: None,
            )
            monkeypatch.setattr(
                ChatEngine,
                "_build_provider",
                lambda self, model_config, force_stream=False: (
                    captured.__setitem__("model_config", model_config),
                    None,
                )[1],
            )

            model_config = resolved_node.model.config if resolved_node.model else None
            reply = await chat_engine._run_agent_turn(
                bot, resolved_node, [], "hello", session,
                model_config=model_config,
            )

            assert "模型配置缺失" in reply
            assert resolved_node.mcps[0].config["url"] == "http://127.0.0.1:18080/mcp"
            assert resolved_node.mcps[0].config["timeout_seconds"] == 45
            captured_model_config = cast(dict[str, object], captured["model_config"])
            assert captured_model_config["api_host"] == "https://api.example.com/v1"
            assert captured_model_config["model_name"] == "gpt-5.2"

        await db_engine.dispose()

    asyncio.run(scenario())


def test_capability_resolver_supports_compensation_mcp_tool_suffix() -> None:
    async def scenario() -> None:
        db_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            session.add(
                CapabilityRegistry(
                    type=CapabilityType.MCP,
                    code="demo_dispatch_mcp",
                    name="Demo Dispatch MCP",
                    status="active",
                    config_json={
                        "client_type": "http_stateless",
                        "transport": "streamable_http",
                        "url": "http://127.0.0.1:18081/mcp",
                    },
                )
            )
            await session.commit()

            resolver = CapabilityResolverService()
            rule = CompensationRule(
                trigger_on=[CompensationTrigger.TIMEOUT],
                action=CompensationAction(
                    type=CompensationActionType.MCP,
                    ref="demo_dispatch_mcp.send_sms",
                    config={},
                    args_mapping={},
                ),
            )

            resolved = await resolver.resolve_compensation_rule(session, rule)

            assert resolved is not None
            assert resolved.action is not None
            assert resolved.action.ref == "demo_dispatch_mcp"
            assert resolved.action.config["url"] == "http://127.0.0.1:18081/mcp"
            assert resolved.action.config["tool_name"] == "send_sms"

        await db_engine.dispose()

    asyncio.run(scenario())


def test_capability_resolver_falls_back_to_virtual_mcp_with_overrides() -> None:
    async def scenario() -> None:
        db_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            session.add(
                CapabilityRegistry(
                    type=CapabilityType.VIRTUAL_MCP,
                    code="ops_tools",
                    name="Ops Tools",
                    status="active",
                    config_json={
                        "mounted_tools": [{"name": "inventory_lookup"}],
                        "timeout_seconds": 30,
                    },
                )
            )
            await session.commit()

            binding = CapabilityBinding(
                ref="ops_tools",
                config={"timeout_seconds": 45},
            )
            resolved = await CapabilityResolverService()._resolve_mcp_or_virtual_binding(
                session, binding
            )

            assert resolved.config["mounted_tools"] == [
                {"name": "inventory_lookup"}
            ]
            assert resolved.config["timeout_seconds"] == 45

        await db_engine.dispose()

    asyncio.run(scenario())


def test_register_mcps_expands_virtual_tools_and_keeps_two_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        db_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        captured: dict[str, object] = {}

        def fake_build_function_tool(**kwargs: object):
            captured.update(kwargs)

            async def invoke(**call_kwargs: object) -> ToolResult:
                return ToolResult(output=call_kwargs)

            return invoke

        monkeypatch.setattr(tr, "build_function_tool", fake_build_function_tool)

        async with session_factory() as session:
            session.add(
                DynamicTool(
                    name="inventory_lookup",
                    description="查询库存",
                    method="POST",
                    url="https://example.test/inventory",
                    headers={"X-Tool": "inventory"},
                    parameters_schema={
                        "type": "object",
                        "properties": {"sku": {"type": "string"}},
                    },
                    status="active",
                )
            )
            await session.commit()

            node = TaskNodeDefinition(
                seq=1,
                code="virtual-node",
                name="Virtual Node",
                mcps=[
                    CapabilityBinding(
                        ref="ops_tools",
                        config={
                            "headers": {"X-Global": "ops"},
                            "mounted_tools": [
                                {
                                    "name": "inventory_lookup",
                                    "response_path": "$.data",
                                    "response_pick": {"$.items": ["sku"]},
                                }
                            ],
                        },
                    )
                ],
            )
            registry = ToolRegistry()
            result = await tr.register_mcps(
                registry,
                node,
                db_session=session,
            )

            assert len(result) == 2
            clients, display_names = result
            assert clients == []
            assert display_names == {
                "inventory_lookup": "ops_tools.inventory_lookup"
            }
            assert registry.is_mcp_tool("inventory_lookup")
            binding_config = cast(dict[str, object], captured["binding_config"])
            assert binding_config["headers"] == {
                "X-Global": "ops",
                "X-Tool": "inventory",
            }
            assert binding_config["response_path"] == "$.data"
            assert binding_config["response_pick"] == {"$.items": ["sku"]}

        await db_engine.dispose()

    asyncio.run(scenario())


def test_resolve_mcp_tool_name_accepts_capability_prefixed_binding_ref() -> None:
    class _Tool:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Client:
        async def list_tools(self) -> list[_Tool]:
            return [_Tool("send_sms"), _Tool("escalate_to_oncall")]

    async def scenario() -> None:
        tool_name, error = await resolve_mcp_tool_name(
            _Client(),
            config={},
            binding_ref="demo_dispatch_mcp.send_sms",
        )
        assert error is None
        assert tool_name == "send_sms"

    asyncio.run(scenario())


def test_build_mcp_client_uses_timeout_seconds_config() -> None:
    client = build_mcp_client(
        {
            "client_type": "http_stateless",
            "transport": "streamable_http",
            "url": "http://127.0.0.1:18080/mcp",
            "timeout_seconds": 45,
        },
        name_hint="demo",
    )

    assert client is not None
    assert getattr(client, "timeout", None) == 45.0
