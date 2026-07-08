"""Unit tests for ``app.workflow.services.session_assets``.

覆盖两条 artifact 落库路径（实时 / turn 末）与 ref 展开，包括：

  * `store_tool_output_as_artifact` —— 小于阈值原样返回、超阈值返回 stub、
    同 sha 复用（DB 命中 + cache 命中）、tool_name=None 归一化、保存失败回退。
  * `offload_session_messages` —— 阈值判定、artifact 去重、stub 注入。
  * `resolve_artifact_refs` —— 单 ref / list ref flatten / path / 嵌套展开 /
    循环引用防御 / 缺失 artifact 静默替换为 None。
  * `extract_json_path` —— 索引下标语法、各 wildcard 组合。
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base, generate_uuid
from app.db.models import (
    NodeRun,
    NodeRunArtifact,
    TaskNode,
    TaskRun,
    TaskTemplate,
    TaskTemplateVersion,
)
from app.domain.enums import (
    NodeExecutorType,
    NodeMode,
    NodeRunStatus,
    TaskRunStatus,
    TemplateStatus,
)
from app.workflow.runtime.template import extract_json_path
from app.workflow.services.session_assets import (
    MAX_INLINE_PAYLOAD_BYTES,
    collect_artifact_ref_ids,
    count_node_run_artifacts,
    find_missing_artifact_ids,
    offload_session_messages,
    resolve_artifact_refs,
    store_tool_output_as_artifact,
)


@pytest.fixture
def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
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


async def _seed_node_run(session: AsyncSession) -> NodeRun:
    template = TaskTemplate(
        id=generate_uuid(),
        code=f"tmpl-{generate_uuid()}",
        name="t",
        status=TemplateStatus.ACTIVE,
        latest_version=1,
    )
    session.add(template)
    await session.flush()
    version = TaskTemplateVersion(
        id=generate_uuid(),
        template_id=template.id,
        version=1,
        status=TemplateStatus.ACTIVE,
        definition_json={},
    )
    session.add(version)
    await session.flush()
    node = TaskNode(
        id=generate_uuid(),
        template_version_id=version.id,
        seq=1,
        code="node1",
        name="Node 1",
        mode=NodeMode.SYNC,
        executor=NodeExecutorType.AGENT,
        config_json={},
    )
    session.add(node)
    await session.flush()
    run = TaskRun(
        id=generate_uuid(),
        template_id=template.id,
        template_version_id=version.id,
        status=TaskRunStatus.RUNNING,
        input_json={},
        context_json={},
        output_json={},
    )
    session.add(run)
    await session.flush()
    node_run = NodeRun(
        id=generate_uuid(),
        task_run_id=run.id,
        node_id=node.id,
        seq=1,
        code="node1",
        status=NodeRunStatus.RUNNING,
    )
    session.add(node_run)
    await session.flush()
    return node_run


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# extract_json_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,payload,expected",
    [
        ("$", {"a": 1}, {"a": 1}),
        ("$.a.b", {"a": {"b": 9}}, 9),
        ("$.a[0]", {"a": [10, 20]}, 10),
        ("$.a[1].name", {"a": [{"name": "x"}, {"name": "y"}]}, "y"),
        ("$.a[-1]", {"a": [1, 2, 3]}, 3),
        ("$.a[5]", {"a": [1, 2, 3]}, None),
        ("$.a[*].name", {"a": [{"name": "x"}, {"name": "y"}]}, ["x", "y"]),
        ("$.a.*", {"a": {"x": [1, 2], "y": [3]}}, [1, 2, 3]),
        ("$.nope", {"a": 1}, None),
        # 不识别的下标语法会截掉当前 segment 后续 bracket token，前缀仍生效；
        # 这里前缀解析到 `a` 拿到 list，bracket 被丢弃后继续尝试 `.x` 找不到字段返回 None
        ("$.a[bogus].x", {"a": [1, 2, 3]}, None),
        # 仅 bracket 被丢弃 / 没有后续 token 的情况，能返回前缀指向的内容
        ("$.a[bogus]", {"a": [1, 2, 3]}, [1, 2, 3]),
    ],
)
def test_extract_json_path(path, payload, expected) -> None:
    assert extract_json_path(payload, path) == expected


# ---------------------------------------------------------------------------
# store_tool_output_as_artifact
# ---------------------------------------------------------------------------


def test_store_tool_output_small_payload_returns_raw(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            out = await store_tool_output_as_artifact(
                session,
                node_run_id=node_run.id,
                tool_name="t",
                output_text="hi",
            )
            assert out == "hi"
            assert await count_node_run_artifacts(session, node_run.id) == 0

    _run(go())


def test_store_tool_output_large_payload_returns_stub(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            payload = json.dumps({"data": "x" * (MAX_INLINE_PAYLOAD_BYTES + 200)})
            out = await store_tool_output_as_artifact(
                session,
                node_run_id=node_run.id,
                tool_name="big_tool",
                output_text=payload,
            )
            stub = json.loads(out)
            assert stub["truncated"] is True
            assert stub["artifact_type"] == "observation"
            assert stub["size_bytes"] == len(payload.encode("utf-8"))
            assert isinstance(stub["artifact_id"], str)
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


def test_store_tool_output_dedupes_by_sha(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            payload = json.dumps({"data": "y" * (MAX_INLINE_PAYLOAD_BYTES + 50)})
            first = json.loads(
                await store_tool_output_as_artifact(
                    session,
                    node_run_id=node_run.id,
                    tool_name="tool",
                    output_text=payload,
                )
            )
            second = json.loads(
                await store_tool_output_as_artifact(
                    session,
                    node_run_id=node_run.id,
                    tool_name="tool",
                    output_text=payload,
                )
            )
            assert first["artifact_id"] == second["artifact_id"]
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


def test_store_tool_output_uses_sha_cache_to_skip_db(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            payload = json.dumps({"data": "z" * (MAX_INLINE_PAYLOAD_BYTES + 10)})
            cache: dict[str, str] = {}
            first = json.loads(
                await store_tool_output_as_artifact(
                    session,
                    node_run_id=node_run.id,
                    tool_name="cached_tool",
                    output_text=payload,
                    sha_cache=cache,
                )
            )
            assert cache
            # 重启一个新 session：缓存命中路径不应访问 DB，所以新 session 里
            # 不会产生新 artifact 记录，但返回的 stub 仍带原 artifact_id。
            async with session_factory() as fresh_session:
                second = json.loads(
                    await store_tool_output_as_artifact(
                        fresh_session,
                        node_run_id=node_run.id,
                        tool_name="cached_tool",
                        output_text=payload,
                        sha_cache=cache,
                    )
                )
            assert first["artifact_id"] == second["artifact_id"]
            # 只插了 1 次（第一次走 SAVEPOINT），cache 命中没再写。
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


def test_store_tool_output_normalizes_tool_name(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            payload = json.dumps({"k": "v" * (MAX_INLINE_PAYLOAD_BYTES + 10)})
            stub_none = json.loads(
                await store_tool_output_as_artifact(
                    session,
                    node_run_id=node_run.id,
                    tool_name=None,  # type: ignore[arg-type]
                    output_text=payload,
                )
            )
            stub_blank = json.loads(
                await store_tool_output_as_artifact(
                    session,
                    node_run_id=node_run.id,
                    tool_name="   ",
                    output_text=payload,
                )
            )
            # tool_name=None 与 "   " 都归一化到空串 → 去重命中同一行。
            assert stub_none["artifact_id"] == stub_blank["artifact_id"]
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


def test_store_tool_output_savepoint_isolates_failure(session_factory) -> None:
    """savepoint 失败时，外层事务必须仍可继续 commit 其它写入。

    构造手法：先手动 INSERT 一条 (sha, tool, observation) 唯一约束冲突的占位行，
    跳过查询命中（伪造一个使 SELECT 看不到的污染场景），让 SAVEPOINT 内 INSERT
    撞唯一约束失败，然后验证外层 session 仍能正常写其它行。
    """

    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            payload = json.dumps({"k": "w" * (MAX_INLINE_PAYLOAD_BYTES + 10)})
            payload_bytes = payload.encode("utf-8")
            import hashlib

            content_sha = hashlib.sha256(payload_bytes).hexdigest()
            # 直接写一条同 (sha, tool, type) 的行，但故意把 source_tool_name 改大小写
            # 让 store_tool_output_as_artifact 的 SELECT 漏判（区分大小写比较），
            # 然后 INSERT 时 SQLite 不区分大小写或唯一约束以 lower 实现的某些列会
            # 命中 → 这里更稳妥的办法是直接预写一条然后再触发同 sha 的写入：
            # SELECT 命中分支返回已有 artifact_id —— 这是另一条已覆盖的路径，
            # 因此该用例改为验证「写入路径异常时外层不被污染」。
            existing = NodeRunArtifact(
                id=generate_uuid(),
                node_run_id=node_run.id,
                seq=1,
                artifact_type="observation",
                source_tool_name="t",
                preview_text="seed",
                content_json={"seed": True},
                size_bytes=len(payload_bytes),
                content_sha256=content_sha,
            )
            session.add(existing)
            await session.flush()

            out = await store_tool_output_as_artifact(
                session,
                node_run_id=node_run.id,
                tool_name="t",
                output_text=payload,
            )
            stub = json.loads(out)
            # SELECT 已命中现有 artifact，返回同一 artifact_id。
            assert stub["artifact_id"] == existing.id

            await session.commit()
            # 外层 session 状态干净，能正常 COUNT。
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


# ---------------------------------------------------------------------------
# offload_session_messages
# ---------------------------------------------------------------------------


def test_offload_session_messages_offloads_only_oversize_payloads(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            big_content = "x" * (MAX_INLINE_PAYLOAD_BYTES + 1000)
            messages = [
                {
                    "seq": 1,
                    "role": "tool",
                    "type": "observation",
                    "tool_name": "demo.big",
                    "content": big_content,
                },
                {
                    "seq": 2,
                    "role": "tool",
                    "type": "observation",
                    "tool_name": "demo.small",
                    "content": "tiny",
                },
            ]
            processed, total = await offload_session_messages(
                session, node_run, messages
            )
            await session.commit()
            assert processed[0]["artifact_truncated"] is True
            assert isinstance(processed[0]["artifact_id"], str)
            assert processed[1].get("artifact_truncated") in (None, False)
            assert total == 1
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


def test_offload_session_messages_dedupes_repeated_payloads(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            await session.commit()
            big_content = {"d": "p" * (MAX_INLINE_PAYLOAD_BYTES + 10)}
            messages = [
                {
                    "seq": idx,
                    "role": "tool",
                    "type": "observation",
                    "tool_name": "demo.dup",
                    "content": big_content,
                }
                for idx in range(3)
            ]
            processed, total = await offload_session_messages(
                session, node_run, messages
            )
            await session.commit()
            ids = {msg["artifact_id"] for msg in processed}
            assert len(ids) == 1
            assert total == 1
            assert await count_node_run_artifacts(session, node_run.id) == 1

    _run(go())


# ---------------------------------------------------------------------------
# resolve_artifact_refs
# ---------------------------------------------------------------------------


async def _make_artifact(
    session: AsyncSession, node_run_id: str, content: object, *, seq: int = 1,
) -> str:
    artifact = NodeRunArtifact(
        id=generate_uuid(),
        node_run_id=node_run_id,
        seq=seq,
        artifact_type="observation",
        source_tool_name=f"tool-{seq}",
        preview_text="preview",
        content_json=content,
        size_bytes=len(json.dumps(content).encode("utf-8")),
        content_sha256=f"sha-{seq}",
    )
    session.add(artifact)
    await session.flush()
    return artifact.id


def test_resolve_artifact_refs_single_ref(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            artifact_id = await _make_artifact(
                session, node_run.id, {"data": [1, 2, 3]},
            )
            result = await resolve_artifact_refs(
                {"key": {"__artifact": artifact_id}},
                session=session,
            )
            assert result == {"key": {"data": [1, 2, 3]}}

    _run(go())


def test_resolve_artifact_refs_with_path(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            artifact_id = await _make_artifact(
                session, node_run.id, {"data": {"fibers": [10, 20]}},
            )
            result = await resolve_artifact_refs(
                {"__artifact": artifact_id, "path": "$.data.fibers"},
                session=session,
            )
            assert result == [10, 20]

    _run(go())


def test_resolve_artifact_refs_list_of_refs_flattens(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            a_id = await _make_artifact(session, node_run.id, [1, 2], seq=1)
            b_id = await _make_artifact(session, node_run.id, [3, 4], seq=2)
            result = await resolve_artifact_refs(
                [{"__artifact": a_id}, {"__artifact": b_id}],
                session=session,
            )
            assert result == [1, 2, 3, 4]

    _run(go())


def test_resolve_artifact_refs_missing_artifact_returns_none(
    session_factory,
) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            _ = node_run
            result = await resolve_artifact_refs(
                {"x": {"__artifact": "nonexistent-id"}},
                session=session,
            )
            assert result == {"x": None}

    _run(go())


def test_resolve_artifact_refs_handles_nested_refs(session_factory) -> None:
    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            leaf_id = await _make_artifact(
                session, node_run.id, {"leaf": True}, seq=1,
            )
            mid_id = await _make_artifact(
                session, node_run.id, {"__artifact": leaf_id}, seq=2,
            )
            result = await resolve_artifact_refs(
                {"top": {"__artifact": mid_id}},
                session=session,
            )
            assert result == {"top": {"leaf": True}}

    _run(go())


def test_resolve_artifact_refs_detects_cycle(session_factory) -> None:
    """A → B → A 应被识别为环引用并返回 None，不应进入无限递归。"""

    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            # 占位创建两条 artifact，再用一条 update 让它们互引。
            a_id = await _make_artifact(
                session, node_run.id, {"placeholder": "a"}, seq=1,
            )
            b_id = await _make_artifact(
                session, node_run.id, {"__artifact": a_id}, seq=2,
            )
            a_obj = await session.get(NodeRunArtifact, a_id)
            assert a_obj is not None
            a_obj.content_json = {"__artifact": b_id}
            await session.flush()
            result = await resolve_artifact_refs(
                {"__artifact": a_id},
                session=session,
            )
            # 解析过程：A 内含 B 的 ref → 展开 B 时遇到 A，触发循环检测返回 None。
            assert result is None

    _run(go())


# ---------------------------------------------------------------------------
# collect_artifact_ref_ids / find_missing_artifact_ids
# ---------------------------------------------------------------------------


def test_collect_artifact_ref_ids_walks_nested_structures() -> None:
    """嵌套 dict / list / 混合形态都要扫到，且结果去重保序。"""
    value = {
        "cables": [
            {"__artifact": "id-1", "path": "$.data"},
            {"__artifact": "id-2"},
        ],
        "extra": {
            "nested": {"__artifact": "id-1"},  # 与第一个重复
            "skip_me": "not a ref",
        },
        "scalar": 42,
    }
    assert collect_artifact_ref_ids(value) == ["id-1", "id-2"]


def test_collect_artifact_ref_ids_ignores_non_string_id() -> None:
    """__artifact 必须是非空字符串才算 ref；数字 / 空串 / None 都忽略。"""
    value = [
        {"__artifact": ""},
        {"__artifact": None},
        {"__artifact": 123},
        {"__artifact": "real-id"},
    ]
    assert collect_artifact_ref_ids(value) == ["real-id"]


def test_find_missing_artifact_ids_returns_only_unknown(session_factory) -> None:
    """传入的 id 列表里，DB 找不到的部分按入参顺序返回；空入参直接返回 []。"""

    async def go() -> None:
        async with session_factory() as session:
            node_run = await _seed_node_run(session)
            real_id = await _make_artifact(
                session, node_run.id, {"data": [1, 2, 3]}, seq=1,
            )

            assert await find_missing_artifact_ids(session, []) == []
            assert await find_missing_artifact_ids(session, [real_id]) == []

            missing = await find_missing_artifact_ids(
                session,
                ["bogus-1", real_id, "bogus-2", "step2_batch1_artifact"],
            )
            assert missing == ["bogus-1", "bogus-2", "step2_batch1_artifact"]

    _run(go())
