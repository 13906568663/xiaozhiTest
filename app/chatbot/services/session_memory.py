"""聊天会话主链路 ``Memory`` 的持久化辅助。

为什么要单独有这层
~~~~~~~~~~~~~~~~~~
``app.runtime_core.compression.maybe_compress`` 把"已经超阈值的早期消息"压成
摘要，写到 :class:`Memory.compressed_summary`，并给被压缩消息打上
``COMPRESSED_MARK``，下一轮 reasoning 就不会再把它们塞进 prompt。

历史实现里 ``ChatEngine._run_agent_turn`` 每次都新建 ``Memory()``，把
``chat_message`` 表里的纯文本逐条 ``add_message`` 进来——也就是说：

* 上一轮压缩出的摘要 + mark **完全没存到 DB**；
* 下一次新请求又从原始 ``chat_message`` 重头塞进 Memory；
* 压缩的"省 token"效果只在单次 HTTP 请求生命周期里存在，跨请求归零。

而 workflow 节点 agent（``NodeRuntime``）这条路径是有持久化的——把
``Memory.state_dict()`` 写在 ``node_run.session_memory_json``，下一轮
``load_state_dict(...)`` 恢复。本模块就是把同一套机制对齐到 chatbot 主链路：
存储位置选 ``ChatSession.context_json["memory"]``，免 schema 迁移。

存储结构
~~~~~~~~
``chat_session.context_json["memory"]`` 形如::

    {
        "content": [[msg_dict, ["compressed", ...]], ...],
        "compressed_summary": "...",
        "last_message_seq": 42  # 见下
    }

其中 ``content`` / ``compressed_summary`` 与 :meth:`Memory.state_dict` 完全
对齐；``last_message_seq`` 是本模块附加的小尾巴，用于「增量追加」：

* 下一次请求加载 Memory 时，先 ``load_state_dict``，然后用
  ``chat_message.seq > last_message_seq`` 的消息把后来落库但未进 Memory 的
  消息（比如客户端断连前 user 已落库但 assistant 没跑完）补回去；
* 没有 ``memory`` 子键的旧会话则走全量 fallback。

写回时机
~~~~~~~~
**仅当本轮 assistant 消息成功 commit 后**才写。失败/异常路径不写——这种
情况下连 user_msg 都被 ``rollback`` 了，下次重试可以从纯 ``chat_message``
兜底。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.chatbot.services.chat_context_ops import merge_context_keys
from app.db.models.chatbot import ChatMessage, ChatSession
from app.runtime_core.memory import Memory
from app.runtime_core.messages import Msg

logger = logging.getLogger(__name__)


MEMORY_KEY = "memory"
LAST_SEQ_KEY = "last_message_seq"

# 与 chat_engine._strip_base64_images 保持一致；这里复制一份避免循环 import。
_BASE64_IMG_RE = re.compile(r"!\[([^\]]*)\]\(data:image/[^)]+\)")
_FILE_DATA_URL_RE = re.compile(r"\n\n\[文件数据:[^\]]*\]\(data:[^)]+\)")


def _strip_base64_images(text: str) -> str:
    text = _BASE64_IMG_RE.sub(r"[\1: 图片已发送给用户]", text)
    text = _FILE_DATA_URL_RE.sub("", text)
    return text


def _coerce_role(raw: str) -> str:
    return raw if raw in ("user", "assistant", "system") else "user"


def _append_chat_message(memory: Memory, msg: ChatMessage) -> None:
    """把单条 ``ChatMessage`` 追加成一条 ``Msg`` 进 ``Memory``。

    目前只还原纯文本 content；``tool_calls_json`` 暂不还原成
    ``tool_use``/``tool_result`` 块（旧会话该字段是 chat_engine 写入的
    "agent_plan/agent_actions"聚合形态，与 Msg 的 OpenAI 风格 tool_calls
    不同构，需要单独的解析器，留给后续 PR）。

    这条 fallback 路径只会在"会话从未被持久化过"或"加载持久化 Memory 后
    需要补 last_message_seq 之后增量"时被命中；正常持久化链路下，所有
    tool_use/tool_result 都已经在 ``Memory.state_dict()`` 里完整保留。
    """
    role = _coerce_role(msg.role)
    content = msg.content or ""
    if content:
        content = _strip_base64_images(content)
    memory.add_message(Msg(role, content))


def build_memory_for_session(
    chat_session: ChatSession,
    history: list[ChatMessage],
) -> Memory:
    """为本轮 ReAct 准备好 ``Memory``。

    优先用 ``chat_session.context_json["memory"]`` 恢复（含
    ``compressed_summary`` 与 ``compressed`` mark）；恢复后再用
    ``last_message_seq`` 之后的 ``chat_message`` 行做增量补齐——一般情况
    下这部分应当为空，除非上一次请求没走完整个写回流程。

    没有 ``memory`` 子键的旧会话退化到「按 chat_message 全量重建」。
    """
    memory = Memory()
    persisted = (chat_session.context_json or {}).get(MEMORY_KEY)

    loaded_from_state = False
    last_seq = 0
    if isinstance(persisted, dict) and persisted.get("content"):
        try:
            memory.load_state_dict(persisted, strict=False)
            loaded_from_state = True
            raw_seq = persisted.get(LAST_SEQ_KEY)
            if isinstance(raw_seq, int):
                last_seq = raw_seq
            else:
                try:
                    last_seq = int(raw_seq) if raw_seq is not None else 0
                except (TypeError, ValueError):
                    last_seq = 0
        except Exception:
            logger.exception(
                "[memory] failed to load persisted state for chat_session=%s, "
                "falling back to full rebuild from chat_message",
                chat_session.id,
            )
            memory = Memory()
            loaded_from_state = False
            last_seq = 0

    if loaded_from_state:
        for msg in history:
            if (msg.seq or 0) > last_seq:
                _append_chat_message(memory, msg)
    else:
        for msg in history:
            _append_chat_message(memory, msg)

    return memory


async def persist_session_memory(
    chat_session_id: str,
    memory: Memory,
    *,
    last_message_seq: int,
    session: AsyncSession | None = None,
) -> None:
    """把 ``Memory.state_dict()`` 合并写回 ``chat_session.context_json["memory"]``。

    用 :func:`chat_context_ops.merge_context_keys` 做字段级 JSONB 原子合并，
    不会覆盖同一行的 ``plan`` / ``embed_*`` 等其它键。

    默认开独立短事务并立即 commit；调用方如果已经在自管理的小事务里，可以
    显式传入 ``session`` 复用。**不要**传入正在持有 ``chat_session`` 行写锁
    的 SSE 长事务——那会把这次写回也压在长锁里，失去并发收益。
    """
    if not chat_session_id:
        return
    state = memory.state_dict()
    payload = dict(state)
    payload[LAST_SEQ_KEY] = int(last_message_seq)
    try:
        await merge_context_keys(
            chat_session_id,
            {MEMORY_KEY: payload},
            session=session,
        )
    except Exception:
        # 持久化失败不应该影响主对话流——记日志即可，下次会从 chat_message
        # 兜底重建。
        logger.exception(
            "[memory] failed to persist state for chat_session=%s",
            chat_session_id,
        )


__all__ = [
    "MEMORY_KEY",
    "LAST_SEQ_KEY",
    "build_memory_for_session",
    "persist_session_memory",
]
