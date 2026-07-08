"""验证 Chatbot.skill_bindings 端到端打通：

* `_build_node_definition` 把 `bot.skill_bindings` 透传成
  `TaskNodeDefinition.skill_codes`；
* `ChatEngine._resolve_node` 走 `CapabilityResolverService` 时显式指定
  ``progressive_skills=True``——只把每条 SKILL.md 的 ``code + description``
  以 ``<available_skills>`` 索引段拼到 system prompt 末尾，**不再注入正文**；
  正文由 `load_skill` 工具按需拉取（见 ``test_chatbot_skill_loader.py``）；
* 停用 / 不存在的 skill code 静默跳过，不影响其它生效项；
* 空 skill_bindings 时 prompt 完全等于原始 system_prompt（零侵入）。

为了避免拉起完整 conversation runtime（涉及模型/MCP 等大量外部依赖），
本测试只走 `_resolve_node` 静态拼接路径——这是 skill 索引注入的**唯一**通道，
能完整覆盖功能正确性。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.chatbot.services.chat_engine import ChatEngine
from app.db.base import Base, generate_uuid
from app.db.models.chatbot import Chatbot
from app.domain.enums import ChatbotStatus, ChatbotType
from app.skill.services import skills as skill_service


SKILL_SOURCE_DEMO = """---
name: demo-orchestrator
description: 当用户提到"圈一片区域 / 处理 XX 批次"时启动演示流水线。
---

# 触发流程
1) 调 open_map_selection
2) 等用户画完多边形
3) 派发 step1
"""

SKILL_SOURCE_GENERIC = """---
name: small-talk-rules
description: 闲聊兜底礼貌话术。
---

# 规则
- 不主动暴露内部模板
- 用户问能干什么时引导他提供圈选区域
"""


@pytest.fixture
def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


async def _seed_skill(
    session: AsyncSession, source: str, *, status: str = "active",
) -> None:
    """走真实 create_skill 服务，让 description 从 frontmatter 自动解析，
    与生产链路一致。"""
    await skill_service.create_skill(
        session, source=source, status=status, created_by=None,
    )


def _make_bot(skill_bindings: list[str] | None = None) -> Chatbot:
    return Chatbot(
        id=generate_uuid(),
        name="演示调度助手",
        description=None,
        type=ChatbotType.NORMAL,
        system_prompt="你是一个调度助手。",
        goal_prompt="",
        model_binding={},
        mcp_bindings=[],
        function_bindings=[],
        knowledge_bindings=[],
        skill_bindings=list(skill_bindings or []),
        max_turns=50,
        status=ChatbotStatus.ACTIVE,
    )


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 单元测试 1：字段直接透传
# ---------------------------------------------------------------------------


def test_build_node_definition_passes_skill_bindings_through() -> None:
    """_build_node_definition 是 Chatbot → TaskNodeDefinition 的唯一桥梁。"""
    bot = _make_bot(skill_bindings=["demo-orchestrator", "small-talk-rules"])
    node_def = ChatEngine._build_node_definition(bot)
    assert node_def.skill_codes == [
        "demo-orchestrator",
        "small-talk-rules",
    ]


def test_build_node_definition_handles_empty_skill_bindings() -> None:
    """空列表 / None 都安全归一为 []。"""
    assert ChatEngine._build_node_definition(_make_bot([])).skill_codes == []
    bot_none = _make_bot()
    bot_none.skill_bindings = None  # type: ignore[assignment]
    assert ChatEngine._build_node_definition(bot_none).skill_codes == []


def test_build_node_definition_strips_garbage_codes() -> None:
    """非字符串 / 空字符串 / 纯空白都不进 skill_codes。"""
    bot = _make_bot()
    bot.skill_bindings = ["valid", "", "  ", None, 123]  # type: ignore[list-item]
    node_def = ChatEngine._build_node_definition(bot)
    assert node_def.skill_codes == ["valid"]


# ---------------------------------------------------------------------------
# 单元测试 2：resolver 把 skill 正文注入 system prompt
# ---------------------------------------------------------------------------


def test_resolve_node_injects_active_skill_index_only(session_factory) -> None:
    """progressive 模式：只注入 code + description 索引，**不带正文**。"""
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_DEMO)
            await _seed_skill(session, SKILL_SOURCE_GENERIC)
            await session.commit()

            engine = ChatEngine()
            bot = _make_bot(
                skill_bindings=["demo-orchestrator", "small-talk-rules"]
            )
            node_def = await engine._resolve_node(session, bot)

            assert "你是一个调度助手。" in node_def.prompt
            assert "<available_skills" in node_def.prompt
            assert "load_skill(code)" in node_def.prompt
            # 索引段：以自闭合 <skill ... /> 形式列出
            assert (
                '<skill code="demo-orchestrator"' in node_def.prompt
            )
            assert "圈一片区域" in node_def.prompt  # description 入索引
            assert '<skill code="small-talk-rules"' in node_def.prompt
            assert "闲聊兜底礼貌话术" in node_def.prompt
            # 正文绝不能出现（按需通过 load_skill 工具拉取）
            assert "调 open_map_selection" not in node_def.prompt
            assert "不主动暴露内部模板" not in node_def.prompt
            assert "</skill>" not in node_def.prompt  # 索引用自闭合，没有闭合标签

    _run(go())


def test_resolve_node_skips_inactive_and_missing_skills(session_factory) -> None:
    """停用的 skill 不入索引；不存在的 code 静默跳过；其余正常生效。"""
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_DEMO)
            await _seed_skill(session, SKILL_SOURCE_GENERIC, status="inactive")
            await session.commit()

            engine = ChatEngine()
            bot = _make_bot(
                skill_bindings=[
                    "demo-orchestrator",
                    "small-talk-rules",
                    "does-not-exist",
                ]
            )
            node_def = await engine._resolve_node(session, bot)

            assert '<skill code="demo-orchestrator"' in node_def.prompt
            assert '<skill code="small-talk-rules"' not in node_def.prompt
            assert "does-not-exist" not in node_def.prompt

    _run(go())


def test_resolve_node_with_empty_skill_bindings_keeps_prompt_intact(
    session_factory,
) -> None:
    """skill_bindings 为空时 system prompt 一字不增。"""
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_DEMO)
            await session.commit()

            engine = ChatEngine()
            bot = _make_bot(skill_bindings=[])
            node_def = await engine._resolve_node(session, bot)

            assert node_def.prompt == "你是一个调度助手。"
            assert "<available_skills" not in node_def.prompt

    _run(go())


# ---------------------------------------------------------------------------
# 单元测试 3：_compose_sys_prompt 把 node_def.prompt（含 skill 索引）作为
# 最终 LLM system_prompt 的起点
#
# 历史上 chat_engine 在拼最终 sys_prompt 时误用 bot.system_prompt 裸字段，
# resolver 注入的 <available_skills> 索引被完全丢弃，chatbot.skill_bindings
# 不生效。本组用例锁住"必须从 node_def.prompt 取"的修复结果，防回归。
# ---------------------------------------------------------------------------


def _make_node_def(prompt: str):
    """造一个最小 TaskNodeDefinition，绕开 capability_resolver 直接喂 _compose_sys_prompt。"""
    from app.workflow.schemas import TaskNodeDefinition

    return TaskNodeDefinition(
        seq=1, code="test-node", name="test", prompt=prompt,
    )


def test_compose_sys_prompt_carries_skill_index_in_normal_mode() -> None:
    """sys_prompt = node_def.prompt + _PLAN_UI_SYSTEM_HINT。"""
    node_def = _make_node_def(
        '你是助手。\n\n<available_skills description="..."><skill code="x" description="y" /></available_skills>'
    )
    sys_prompt = ChatEngine._compose_sys_prompt(node_def)
    assert "你是助手。" in sys_prompt
    assert "<available_skills" in sys_prompt
    assert '<skill code="x"' in sys_prompt
    # PlanNotebook 提示词也应该被拼在末尾
    from app.chatbot.services.chat_engine import _PLAN_UI_SYSTEM_HINT

    assert _PLAN_UI_SYSTEM_HINT in sys_prompt


def test_compose_sys_prompt_falls_back_when_empty() -> None:
    """node_def.prompt 完全为空时降级到默认招呼语。"""
    node_def = _make_node_def("")
    sys_prompt = ChatEngine._compose_sys_prompt(node_def)
    assert "你是一个有帮助的助手" in sys_prompt
    from app.chatbot.services.chat_engine import _PLAN_UI_SYSTEM_HINT

    assert _PLAN_UI_SYSTEM_HINT in sys_prompt


def test_compose_sys_prompt_uses_resolved_prompt_not_bot_system_prompt(
    session_factory,
) -> None:
    """端到端：模拟生产链路 _resolve_node → _compose_sys_prompt，断言最终
    sys_prompt 真的包含了 skill 索引段，从根上锁住 bug 修复。"""
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_DEMO)
            await session.commit()

            engine = ChatEngine()
            bot = _make_bot(skill_bindings=["demo-orchestrator"])
            node_def = await engine._resolve_node(session, bot)

            sys_prompt = ChatEngine._compose_sys_prompt(node_def)

            assert "你是一个调度助手。" in sys_prompt  # bot 原始 system_prompt
            assert "<available_skills" in sys_prompt  # resolver 注入的索引段
            assert '<skill code="demo-orchestrator"' in sys_prompt
            assert "圈一片区域" in sys_prompt  # frontmatter description 进了索引
            # 正文严禁出现在 sys_prompt（progressive 模式下应走 load_skill）
            assert "调 open_map_selection" not in sys_prompt

    _run(go())
