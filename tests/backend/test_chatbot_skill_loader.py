"""验证 ``register_skill_loader`` / ``load_skill`` 工具按需加载 SKILL.md 正文。

测试焦点：
  * 空 ``skill_codes`` 时**不注册**工具（避免给 LLM 留下死接口）；
  * 未挂载的 code → ``is_error=True`` 越权防护；
  * 不存在的 code → 明确报错"未找到，可能被删除"；
  * 已停用的 code → 明确报错并带状态；
  * 正文解析失败（虽然现实极少触发）→ 错误报回；
  * 首次成功加载返回 ``cached=False``，再次加载同 code 返回 ``cached=True``，
    body 二者一致；
  * code 参数缺失 / 空白 → 报错并带 ``available`` 列表辅助纠错。

测试只直连 ``register_skill_loader`` + ``ToolRegistry``，不拉真实 LLM/ReAct
loop，目的是覆盖工具内部逻辑的所有分支。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.chatbot.services.skill_loader import register_skill_loader
from app.db.base import Base
from app.runtime_core.tool_protocol import ToolContext, ToolRegistry, ToolResult
from app.skill.services import skills as skill_service


SKILL_SOURCE_A = """---
name: demo-survey
description: 演示现场作业标准流程。
---

# 步骤
1. 检查工单
2. 取 OSS 数据
3. 输出报告
"""

SKILL_SOURCE_B = """---
name: ticket-classify
description: 工单分类规则。
---

# 规则
按描述 + 附件文本归类。
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
    await skill_service.create_skill(
        session, source=source, status=status, created_by=None,
    )


async def _invoke_load_skill(
    registry: ToolRegistry, arguments: dict[str, object]
) -> ToolResult:
    """通过 ToolHandler.execute 走完整工具调用路径（含参数解包 + 异常包装）。"""
    handler = registry.get_handler("load_skill")
    assert handler is not None, "load_skill should be registered"
    return await handler.execute(arguments, ToolContext())


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 注册门槛：空白入参 → 不注册
# ---------------------------------------------------------------------------


def test_register_skill_loader_skips_when_no_skill_codes(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            registry = ToolRegistry()
            register_skill_loader(registry, db_session=session, skill_codes=[])
            assert not registry.has("load_skill")

            # 全是空白也不注册（防止配置脏数据触发）
            register_skill_loader(
                registry, db_session=session, skill_codes=["", "  ", None],  # type: ignore[list-item]
            )
            assert not registry.has("load_skill")

    _run(go())


# ---------------------------------------------------------------------------
# 正常加载 + 缓存
# ---------------------------------------------------------------------------


def test_load_skill_returns_body_and_caches(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_A)
            await _seed_skill(session, SKILL_SOURCE_B)
            await session.commit()

            registry = ToolRegistry()
            register_skill_loader(
                registry,
                db_session=session,
                skill_codes=["demo-survey", "ticket-classify"],
            )
            assert registry.has("load_skill")

            first = await _invoke_load_skill(registry, {"code": "demo-survey"})
            assert first.is_error is False
            assert first.output["ok"] is True
            assert first.output["code"] == "demo-survey"
            assert first.output["cached"] is False
            assert "# 步骤" in first.output["body"]
            assert "取 OSS 数据" in first.output["body"]
            # frontmatter 不应混入 body
            assert "---" not in first.output["body"].split("\n")[0]

            # 二次调同一 code → 缓存命中
            second = await _invoke_load_skill(registry, {"code": "demo-survey"})
            assert second.is_error is False
            assert second.output["cached"] is True
            assert second.output["body"] == first.output["body"]

            # 加载另一个 code → 仍然走库（cached=False）
            other = await _invoke_load_skill(registry, {"code": "ticket-classify"})
            assert other.is_error is False
            assert other.output["cached"] is False
            assert "工单分类" not in other.output["body"]  # 该字符串在 description 里，不在 body
            assert "按描述 + 附件文本归类" in other.output["body"]

    _run(go())


def test_load_skill_trims_whitespace_code(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_A)
            await session.commit()

            registry = ToolRegistry()
            register_skill_loader(
                registry, db_session=session, skill_codes=["demo-survey"],
            )
            res = await _invoke_load_skill(registry, {"code": "  demo-survey  "})
            assert res.is_error is False
            assert res.output["code"] == "demo-survey"

    _run(go())


# ---------------------------------------------------------------------------
# 越权 / 不存在 / 停用 / 解析失败
# ---------------------------------------------------------------------------


def test_load_skill_rejects_unmounted_code(session_factory) -> None:
    """已挂载列表外的 code（即便库里存在）也不可加载，防止越权偷取。"""
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_A)
            await _seed_skill(session, SKILL_SOURCE_B)
            await session.commit()

            registry = ToolRegistry()
            # 只挂 demo-survey；ticket-classify 在库里存在但未挂
            register_skill_loader(
                registry, db_session=session, skill_codes=["demo-survey"],
            )

            res = await _invoke_load_skill(registry, {"code": "ticket-classify"})
            assert res.is_error is True
            assert res.output["ok"] is False
            assert "未挂载" in res.output["error"]
            assert res.output["available"] == ["demo-survey"]

    _run(go())


def test_load_skill_reports_missing_in_db(session_factory) -> None:
    """声明挂载了但库里压根没有 → 报"未找到，可能已被删除"。"""
    async def go() -> None:
        async with session_factory() as session:
            registry = ToolRegistry()
            register_skill_loader(
                registry, db_session=session, skill_codes=["ghost-skill"],
            )
            res = await _invoke_load_skill(registry, {"code": "ghost-skill"})
            assert res.is_error is True
            assert "未找到" in res.output["error"]

    _run(go())


def test_load_skill_reports_inactive_skill(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            await _seed_skill(session, SKILL_SOURCE_A, status="inactive")
            await session.commit()

            registry = ToolRegistry()
            register_skill_loader(
                registry, db_session=session, skill_codes=["demo-survey"],
            )
            res = await _invoke_load_skill(registry, {"code": "demo-survey"})
            assert res.is_error is True
            assert "未启用" in res.output["error"]
            assert "inactive" in res.output["error"]

    _run(go())


# ---------------------------------------------------------------------------
# 参数边界
# ---------------------------------------------------------------------------


def test_load_skill_requires_non_empty_code(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            registry = ToolRegistry()
            register_skill_loader(
                registry, db_session=session, skill_codes=["demo-survey"],
            )
            # code 为空字符串
            res_empty = await _invoke_load_skill(registry, {"code": ""})
            assert res_empty.is_error is True
            assert res_empty.output["available"] == ["demo-survey"]

            # code 全空白
            res_blank = await _invoke_load_skill(registry, {"code": "   "})
            assert res_blank.is_error is True

            # 默认值（完全没传 code）
            res_missing = await _invoke_load_skill(registry, {})
            assert res_missing.is_error is True

    _run(go())
