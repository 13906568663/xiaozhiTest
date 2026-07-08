from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import NodeRun, NodeRunArtifact
from app.workflow.runtime.helpers import snapshot_json
from app.workflow.runtime.template import extract_json_path
from app.workflow.runtime.types import SessionTurnAction, SessionTurnResult


logger = logging.getLogger(__name__)

# Artifact 体积阈值（字节）。OFFLOAD 与 IMMEDIATE 两条路径统一按 UTF-8 字节判定，
# 避免「字符 vs 字节」在中文场景下造成阈值不对称（一个汉字 3 字节）。
MAX_INLINE_PAYLOAD_BYTES = 1800
# 向下兼容的旧名（如果外部模块还在 import 这个常量，不要硬切）。
MAX_INLINE_SESSION_PAYLOAD_CHARS = MAX_INLINE_PAYLOAD_BYTES
MAX_PREVIEW_CHARS = 120
# artifact 引用协议：在 result 的任意层级用 {"__artifact": "<id>"} 或
# {"__artifact": "<id>", "path": "$.data.fibers"} 表示「此处指向某次工具调用
# 返回的 raw 大数据」。NodeRuntime 完成节点时会自动把这些引用展开成实际内容
# （读 node_run_artifact.content_json），从而让 LLM 不必把大数据再 token-by-token
# 输出一遍，绕开 max_tokens 截断风险。
ARTIFACT_REF_KEY = "__artifact"
ARTIFACT_REF_PATH_KEY = "path"
# artifact 引用展开深度上限，防止 LLM 误生成自引用 / 循环 ref 把递归打爆。
MAX_ARTIFACT_REF_DEPTH = 16

# 空串作为「无来源工具」的哨兵。Postgres 唯一约束对 NULL 列视为「互不相等」，
# 改空串后 (node_run_id, sha, artifact_type, source_tool_name) 的去重才真生效。
_NO_TOOL = ""
_INTERNAL_TOOL_PREFIXES = (
    "workflow_",
    "FlowLifecycle_",
    "FlowSleep_",
    "FlowCallback_",
    "FlowRuntime_",
)


def _json_text(value: Any) -> str:
    return json.dumps(
        snapshot_json(value),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _canonical_payload(value: Any) -> tuple[str, bytes, str]:
    """把任意 value 收敛成 ``(canonical_text, canonical_bytes, sha256)``。

    两条 artifact 落库路径（即时 / turn 末）共用此 helper，保证同一份内容的
    sha 与 size_bytes 始终一致 —— 这是去重和体积统计正确的前提。
    """
    text = _json_text(value)
    encoded = text.encode("utf-8")
    return text, encoded, hashlib.sha256(encoded).hexdigest()


def _preview_text(value: Any, *, max_chars: int = MAX_PREVIEW_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        raw = value
    else:
        raw = _json_text(value)
    compact = " ".join(raw.split()).strip()
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1]}…"


def _normalize_tool_name(value: Any) -> str:
    """统一 source_tool_name 写库口径：去空白；None / 空 → 空串。"""
    if value is None:
        return _NO_TOOL
    stripped = str(value).strip()
    return stripped or _NO_TOOL


def _artifact_stub(
    *,
    artifact_id: str,
    preview: str,
    artifact_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    """统一的 artifact 占位结构。

    与历史版本不同，stub 不再嵌入冗长的「如何用 __artifact 引用」中文说明
    （之前每条 stub ≈ 300 token，单 turn 多次调用会重复消耗）。该说明现在
    集中放到节点系统提示词里讲一次，参见 ``prompt._build_output_result_hint``。
    """
    return {
        "artifact_id": artifact_id,
        "preview": preview,
        "truncated": True,
        "artifact_type": artifact_type,
        "size_bytes": size_bytes,
    }


def _artifact_candidate(message: dict[str, Any]) -> tuple[str, Any, str] | None:
    message_type = str(message.get("type") or "")
    if message_type == "action" and "arguments" in message:
        return ("arguments", message.get("arguments"), "action")
    if message_type in {"observation", "final"} and "content" in message:
        return ("content", message.get("content"), message_type)
    return None


def _is_internal_tool(tool_name: str | None) -> bool:
    if not tool_name:
        return False
    return tool_name.startswith(_INTERNAL_TOOL_PREFIXES)


async def offload_session_messages(
    session: AsyncSession,
    node_run: NodeRun,
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """扫描 messages，把超阈值 payload 落 artifact + 替换为 stub。

    第二项返回值是「本 node_run 累计 artifact 总数」（含历史 + 本次新写）。
    注意：实时落库路径（:func:`store_tool_output_as_artifact`）的产物已在
    turn 内被替换成 stub，不会再次出现在 messages 里；但同 node_run 内任何
    路径写过的 artifact 都计入返回的总数。
    """
    # 不再加载 content_json（大列），降低 turn 持久化阶段 IO；其余字段足够做去重。
    stmt = (
        sa.select(
            NodeRunArtifact.id,
            NodeRunArtifact.seq,
            NodeRunArtifact.content_sha256,
            NodeRunArtifact.artifact_type,
            NodeRunArtifact.source_tool_name,
            NodeRunArtifact.preview_text,
            NodeRunArtifact.size_bytes,
        )
        .where(NodeRunArtifact.node_run_id == node_run.id)
        .order_by(NodeRunArtifact.seq)
    )
    rows = list((await session.execute(stmt)).all())
    artifact_map: dict[tuple[str, str, str], dict[str, Any]] = {
        (
            row.content_sha256,
            row.artifact_type,
            _normalize_tool_name(row.source_tool_name),
        ): {
            "id": row.id,
            "seq": row.seq,
            "artifact_type": row.artifact_type,
            "preview_text": row.preview_text,
            "size_bytes": row.size_bytes,
        }
        for row in rows
    }
    next_seq = max((row.seq for row in rows), default=0) + 1

    processed_messages: list[dict[str, Any]] = []
    for message in messages:
        next_message = snapshot_json(message)
        candidate = _artifact_candidate(next_message)
        if candidate is None:
            processed_messages.append(next_message)
            continue

        field_name, payload, artifact_type = candidate
        _, payload_bytes, content_sha256 = _canonical_payload(payload)
        if len(payload_bytes) <= MAX_INLINE_PAYLOAD_BYTES:
            processed_messages.append(next_message)
            continue

        tool_name = _normalize_tool_name(next_message.get("tool_name"))
        preview = _preview_text(payload)
        size_bytes = len(payload_bytes)
        artifact_key = (content_sha256, artifact_type, tool_name)
        artifact_entry = artifact_map.get(artifact_key)
        if artifact_entry is None:
            artifact_id = generate_uuid()
            session.add(
                NodeRunArtifact(
                    id=artifact_id,
                    node_run_id=node_run.id,
                    seq=next_seq,
                    artifact_type=artifact_type,
                    source_tool_name=tool_name,
                    preview_text=preview,
                    content_json=snapshot_json(payload),
                    size_bytes=size_bytes,
                    content_sha256=content_sha256,
                )
            )
            artifact_entry = {
                "id": artifact_id,
                "seq": next_seq,
                "artifact_type": artifact_type,
                "preview_text": preview,
                "size_bytes": size_bytes,
            }
            artifact_map[artifact_key] = artifact_entry
            next_seq += 1

        stub = _artifact_stub(
            artifact_id=artifact_entry["id"],
            preview=artifact_entry["preview_text"] or preview,
            artifact_type=artifact_entry["artifact_type"],
            size_bytes=artifact_entry["size_bytes"],
        )
        next_message[field_name] = stub
        next_message["artifact_id"] = artifact_entry["id"]
        next_message["artifact_preview"] = stub["preview"]
        next_message["artifact_truncated"] = True
        next_message["artifact_type"] = artifact_entry["artifact_type"]
        processed_messages.append(next_message)

    return processed_messages, len(artifact_map)


def build_turn_summary(
    result: SessionTurnResult,
    messages: list[dict[str, Any]],
) -> str | None:
    summary = (result.summary or "").strip()
    if summary:
        return summary

    runtime_summary = str((result.runtime_state or {}).get("_summary") or "").strip()
    if runtime_summary:
        return runtime_summary

    for message in reversed(messages):
        if message.get("type") == "final":
            preview = _preview_text(message.get("content"))
            if preview:
                return preview

    if result.action == SessionTurnAction.WAIT_CALLBACK:
        return "已进入外部回调等待"
    if result.action == SessionTurnAction.WAIT_TIMER:
        return "已进入定时等待"
    if result.action == SessionTurnAction.FAIL:
        error_message = (result.error_message or "").strip()
        return error_message or "节点执行失败"
    if result.action == SessionTurnAction.COMPLETE:
        return "节点执行完成"
    return None


async def store_tool_output_as_artifact(
    session: AsyncSession,
    *,
    node_run_id: str,
    tool_name: str,
    output_text: str,
    threshold_bytes: int = MAX_INLINE_PAYLOAD_BYTES,
    sha_cache: dict[str, str] | None = None,
) -> str:
    """**即时**把超大工具返回存为 NodeRunArtifact，返回一个 stub JSON 字符串。

    与 :func:`offload_session_messages` 的区别：
      * offload 在节点持久化（turn 结束）时才扫描 messages 提取 artifact —— LLM
        在当前 turn 内拿到的是 raw 大对象。
      * 本函数在工具调用**当场**调用（通过
        ``ConversationRuntime.tool_output_postprocessor`` 钩子），把 raw 替换成
        stub，**LLM 在下一个 iter 立即看到 artifact_id**，因此可以在最终
        ``generate_response`` 里用 ``{"__artifact": "<id>"}`` 引用。

    超过 ``threshold_bytes`` 字节才会落 artifact；否则原样返回 ``output_text``。
    artifact 同 ``(content_sha256, tool_name)`` 在同一 node_run 下会被去重复用。

    Args:
        sha_cache: 可选的 turn 级缓存（``sha:tool_name -> artifact_id``），允许
            同 turn 内重复调用直接命中 stub，避免每次都 SELECT 一次 DB。

    异常处理：
      * insert 走 SAVEPOINT（``session.begin_nested()``），失败时单独回滚，
        外层事务不会被拖入 ``PendingRollbackError`` 状态。
      * 查询失败或缺失 ``node_run_id`` 时返回原 ``output_text``，不阻断工具链。
    """
    if not node_run_id:
        return output_text

    payload_bytes = output_text.encode("utf-8")
    size_bytes = len(payload_bytes)
    if size_bytes <= threshold_bytes:
        return output_text

    normalized_tool = _normalize_tool_name(tool_name)
    content_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    cache_key = f"{content_sha256}:{normalized_tool}"

    if sha_cache is not None and cache_key in sha_cache:
        artifact_id = sha_cache[cache_key]
        stub = _artifact_stub(
            artifact_id=artifact_id,
            preview=_preview_text(output_text),
            artifact_type="observation",
            size_bytes=size_bytes,
        )
        return json.dumps(stub, ensure_ascii=False)

    try:
        parsed_content: Any = json.loads(output_text)
    except (TypeError, ValueError):
        parsed_content = {"text": output_text}

    try:
        existing = await session.scalar(
            sa.select(NodeRunArtifact).where(
                NodeRunArtifact.node_run_id == node_run_id,
                NodeRunArtifact.content_sha256 == content_sha256,
                NodeRunArtifact.source_tool_name == normalized_tool,
                NodeRunArtifact.artifact_type == "observation",
            )
        )
    except Exception:
        logger.exception(
            "store_tool_output_as_artifact: 查询 artifact 失败，回退到原 output（tool=%s）",
            normalized_tool,
        )
        return output_text

    if existing is not None:
        artifact_id = existing.id
        size_bytes = existing.size_bytes
        preview = existing.preview_text or _preview_text(parsed_content)
    else:
        preview = _preview_text(parsed_content)
        try:
            max_seq = await session.scalar(
                sa.select(
                    sa.func.coalesce(sa.func.max(NodeRunArtifact.seq), 0)
                ).where(NodeRunArtifact.node_run_id == node_run_id)
            )
        except Exception:
            logger.exception(
                "store_tool_output_as_artifact: 查询 max(seq) 失败（tool=%s），回退到原 output",
                normalized_tool,
            )
            return output_text
        next_seq = int(max_seq or 0) + 1
        artifact_id = generate_uuid()
        try:
            async with session.begin_nested():
                session.add(
                    NodeRunArtifact(
                        id=artifact_id,
                        node_run_id=node_run_id,
                        seq=next_seq,
                        artifact_type="observation",
                        source_tool_name=normalized_tool,
                        preview_text=preview,
                        content_json=parsed_content,
                        size_bytes=size_bytes,
                        content_sha256=content_sha256,
                    )
                )
        except Exception:
            # SAVEPOINT 已自动回滚，外层事务依然干净；回退到原 output 即可。
            logger.exception(
                "store_tool_output_as_artifact: 写入 artifact 失败（tool=%s），回退到原 output",
                normalized_tool,
            )
            return output_text

    if sha_cache is not None:
        sha_cache[cache_key] = artifact_id

    stub = _artifact_stub(
        artifact_id=artifact_id,
        preview=preview,
        artifact_type="observation",
        size_bytes=size_bytes,
    )
    return json.dumps(stub, ensure_ascii=False)


def _is_artifact_ref(value: Any) -> bool:
    """判断 value 是否为 ``{"__artifact": "<id>", ...}`` 形式的引用对象。"""
    return (
        isinstance(value, dict)
        and isinstance(value.get(ARTIFACT_REF_KEY), str)
        and bool(value.get(ARTIFACT_REF_KEY))
    )


def is_artifact_ref(value: Any) -> bool:
    """公开 API：判断 value 是否为 artifact ref dict（供 prompt / template 渲染层用）。"""
    return _is_artifact_ref(value)


def is_artifact_ref_list(value: Any) -> bool:
    """判断 value 是否是「全部元素都是 artifact ref」的列表。

    `resolve_artifact_refs` 对这种列表会做 flatten 展开成大列表，因此渲染层
    遇到它必须按"摘要"处理，绝不能内嵌到 prompt token。
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(_is_artifact_ref(item) for item in value)
    )


def summarize_artifact_value(value: Any) -> str | None:
    """把 artifact ref 或 ref list 渲染成 prompt 安全的摘要文本。

    返回 ``None`` 表示 value 不是 artifact 相关结构（调用方按常规渲染）。
    返回字符串则可直接作为占位符替换值，**不会引入大体积 JSON**。
    """
    if _is_artifact_ref(value):
        aid = value.get(ARTIFACT_REF_KEY)
        path = value.get(ARTIFACT_REF_PATH_KEY)
        if path:
            return f"<artifact id={aid} path={path}>"
        return f"<artifact id={aid}>"
    if is_artifact_ref_list(value):
        ids = [str(item.get(ARTIFACT_REF_KEY)) for item in value]
        sample = ", ".join(ids[:3])
        more = f", 共 {len(ids)} 个" if len(ids) > 3 else ""
        first_path = value[0].get(ARTIFACT_REF_PATH_KEY) if value else None
        path_hint = f" path={first_path}" if first_path else ""
        return f"<artifact-list ids=[{sample}{more}]{path_hint}>"
    return None


def collect_artifact_summary(value: Any) -> dict[str, Any] | None:
    """递归扫描 value，统计 artifact 数量与采样 id，供 prompt 摘要使用。

    与 :func:`summarize_artifact_value` 不同：本函数处理「内部嵌套含 ref 的复合
    对象」（如 ``{"fibers": <ref-list>, "fiber_names": ["..."]}``），目的是让
    LLM 知道这个字段「不是空，里面有 N 个 artifact」而不需要展开。
    """
    ref_ids: list[str] = []
    total_size_bytes = 0

    def _walk(node: Any) -> None:
        nonlocal total_size_bytes
        if isinstance(node, dict):
            if _is_artifact_ref(node) and set(node.keys()) <= {
                ARTIFACT_REF_KEY,
                ARTIFACT_REF_PATH_KEY,
            }:
                ref_ids.append(str(node[ARTIFACT_REF_KEY]))
                return
            for v in node.values():
                _walk(v)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(value)
    if not ref_ids:
        return None
    return {
        "artifact_count": len(ref_ids),
        "artifact_ids": ref_ids[:5],
        "approx_size_bytes": total_size_bytes,
    }


async def _load_artifact_content(
    session: AsyncSession,
    artifact_id: str,
    path: str | None,
) -> Any:
    """按 artifact_id 加载内容，按需用 ``$.a.b`` 路径抽取子树。

    缺失或路径不匹配时返回 ``None`` 并打 warning，不抛异常 —— 保持引擎健壮性：
    artifact 解析是优化通道，单条缺失不应让整个节点 / 任务跑挂。
    """
    artifact = await session.get(NodeRunArtifact, artifact_id)
    if artifact is None or artifact.content_json is None:
        logger.warning(
            "resolve_artifact_refs: artifact %s 不存在或 content 为空，已替换为 None",
            artifact_id,
        )
        return None

    content: Any = artifact.content_json
    # NodeRunArtifact.content_json 历史上既有"原生 dict/list"也有"嵌套字符串"两种存法
    # （取决于 SQLAlchemy 列定义与写入路径），统一兜底解析一次：当字符串时尝试 json.loads。
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return content if path is None else None

    if path:
        extracted = extract_json_path(content, path)
        if extracted is None:
            logger.warning(
                "resolve_artifact_refs: artifact %s 的 path %r 未匹配到，已替换为 None",
                artifact_id,
                path,
            )
        return extracted
    return content


async def resolve_artifact_refs(
    value: Any,
    *,
    session: AsyncSession,
    _depth: int = 0,
    _visited: frozenset[str] | None = None,
) -> Any:
    """递归把 ``value`` 中所有 ``{"__artifact": "<id>", "path"?: ...}`` 引用替换为实际内容。

    替换规则：
      * dict 自身是 ref（且只含 ``__artifact``/``path`` 键） —— 整个替换为
        artifact 内容；若 artifact 内容里**还有 ref**（例如上游节点把 stub
        当 result 转交），会继续递归展开。
        若 dict 还有 ref 之外的其他键，则视为业务 dict，逐键递归。
      * list 中所有元素都是 ref —— 逐个 fetch（含嵌套展开）后做 flatten 合并：
          - artifact 内容是 list → ``extend``
          - artifact 内容是 dict / scalar → ``append``
        这样 LLM 可以把多次工具调用产生的 artifact_id 简单列成数组，runtime
        自动合并出"大表"。
      * 其他情况 —— 普通递归。

    防御：``_visited`` 跟踪当前展开链路上的 artifact_id，A→B→A 这种环引用
    会被识别并替换为 ``None``；嵌套深度上限为 :data:`MAX_ARTIFACT_REF_DEPTH`，
    超过即停止展开以保证最坏情况可终止。
    """
    if _depth >= MAX_ARTIFACT_REF_DEPTH:
        logger.warning(
            "resolve_artifact_refs: 嵌套深度超过 %d，停止展开",
            MAX_ARTIFACT_REF_DEPTH,
        )
        return value

    visited = _visited or frozenset()

    if isinstance(value, dict):
        if _is_artifact_ref(value) and set(value.keys()) <= {
            ARTIFACT_REF_KEY,
            ARTIFACT_REF_PATH_KEY,
        }:
            artifact_id = str(value[ARTIFACT_REF_KEY])
            if artifact_id in visited:
                logger.warning(
                    "resolve_artifact_refs: 检测到 artifact 循环引用 %s，已替换为 None",
                    artifact_id,
                )
                return None
            loaded = await _load_artifact_content(
                session, artifact_id, value.get(ARTIFACT_REF_PATH_KEY),
            )
            return await resolve_artifact_refs(
                loaded,
                session=session,
                _depth=_depth + 1,
                _visited=visited | {artifact_id},
            )
        return {
            key: await resolve_artifact_refs(
                item,
                session=session,
                _depth=_depth,
                _visited=visited,
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        if value and all(_is_artifact_ref(item) for item in value):
            merged: list[Any] = []
            for ref in value:
                artifact_id = str(ref[ARTIFACT_REF_KEY])
                if artifact_id in visited:
                    logger.warning(
                        "resolve_artifact_refs: 检测到 artifact 循环引用 %s，已跳过",
                        artifact_id,
                    )
                    continue
                content = await _load_artifact_content(
                    session, artifact_id, ref.get(ARTIFACT_REF_PATH_KEY),
                )
                expanded = await resolve_artifact_refs(
                    content,
                    session=session,
                    _depth=_depth + 1,
                    _visited=visited | {artifact_id},
                )
                if expanded is None:
                    continue
                if isinstance(expanded, list):
                    merged.extend(expanded)
                else:
                    merged.append(expanded)
            return merged
        return [
            await resolve_artifact_refs(
                item,
                session=session,
                _depth=_depth,
                _visited=visited,
            )
            for item in value
        ]

    return value


def build_last_tool_summary(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        message_type = str(message.get("type") or "")
        if message_type not in {"action", "observation"}:
            continue

        tool_name = str(message.get("tool_name") or "").strip() or None
        if _is_internal_tool(tool_name):
            continue

        payload = (
            message.get("content")
            if message_type == "observation"
            else message.get("arguments")
        )
        preview = _preview_text(payload, max_chars=80)
        tool_label = tool_name or "外部能力"
        if message_type == "observation":
            return f"{tool_label} · {preview}" if preview else tool_label
        return f"调用 {tool_label} · {preview}" if preview else f"调用 {tool_label}"

    return None


async def count_node_run_artifacts(session: AsyncSession, node_run_id: str) -> int:
    """返回某 node_run 累计的 artifact 总数（即时路径 + offload 路径，去重）。"""
    if not node_run_id:
        return 0
    total = await session.scalar(
        sa.select(sa.func.count(NodeRunArtifact.id)).where(
            NodeRunArtifact.node_run_id == node_run_id,
        )
    )
    return int(total or 0)


def collect_artifact_ref_ids(value: Any) -> list[str]:
    """递归扫出 ``value`` 中所有 ``{"__artifact": "<id>", ...}`` 引用的 id 字面量。

    用于在节点完成、写回 context 之前做一次「LLM 引用的 artifact 是否真实存在」的
    校验。返回的列表保留出现顺序但已去重 —— 调用方通常只关心唯一 id 集合。
    """
    seen: dict[str, None] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if _is_artifact_ref(node):
                seen.setdefault(str(node[ARTIFACT_REF_KEY]), None)
                # ref dict 里业务键也可能再藏 ref（罕见但合法），继续递归非 key
                for k, v in node.items():
                    if k in {ARTIFACT_REF_KEY, ARTIFACT_REF_PATH_KEY}:
                        continue
                    _walk(v)
                return
            for v in node.values():
                _walk(v)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(value)
    return list(seen.keys())


async def find_missing_artifact_ids(
    session: AsyncSession, candidate_ids: list[str]
) -> list[str]:
    """返回 ``candidate_ids`` 中 ``node_run_artifact`` 表里**没有**对应行的 id 列表。

    用于「LLM 在 result 里编造了不存在的 artifact_id」的兜底检测：调用方拿到非空
    返回应当把节点标记 FAILED 并给出可读 error_message，而不是让 resolve_artifact_refs
    悄悄返回 ``None`` —— 那种静默行为会把下游 context 污染成空列表/空 dict，
    流水线后续节点照常 "complete"，问题被埋到很远才暴露。
    """
    if not candidate_ids:
        return []
    existing = set(
        (await session.scalars(
            sa.select(NodeRunArtifact.id).where(
                NodeRunArtifact.id.in_(candidate_ids)
            )
        )).all()
    )
    return [aid for aid in candidate_ids if aid not in existing]
