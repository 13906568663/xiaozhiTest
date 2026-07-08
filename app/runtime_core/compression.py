"""会话历史压缩 / 续接（fool-code 风格复刻 + agent-flow 单字段存储）。

为什么不用结构化输出
~~~~~~~~~~~~~~~~~~~~~
国内常见 OpenAI 兼容供应商（DashScope / Moonshot / 智谱 / 自建网关）对
``response_format=json_schema`` 支持参差不齐，命中即 400。所以我们让模型
输出纯文本（带 ``<analysis>``/``<summary>`` 标签的 Markdown），自己解析。

复刻 fool-code 的几个关键点
~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **分两步思考**：让模型先在 ``<analysis>`` 里逐条捋一遍历史，再在
   ``<summary>`` 里输出最终摘要——比直接要总结质量稳得多。
2. **九段大纲**：主要请求和意图 / 关键技术概念 / 文件和代码部分 / 错误
   和修复 / 问题解决 / 所有用户消息 / 待处理任务 / 当前工作 / 可选的
   下一步。覆盖业务调度 + 代码 agent 双场景。
3. **续接消息**：摘要前后会拼三段固定 preamble：
   - 前缀：「本次会话是从之前的对话延续的……」让模型明确"接着上次继续"
   - 中段：「最近的消息已原样保留」
   - 末尾：「从上次中断的地方继续，不要确认摘要、不要回顾」
4. **多次合并**：``_merge_compact_summaries`` 把"之前压缩"+"新压缩"叠在
   一起，避免长 session 反复压缩时丢失早期上下文。
5. **规则兜底**：LLM 调用失败 / 返回空时，退化到统计 + 最近用户消息 +
   关键文件抽取的纯规则摘要——保证「永远有摘要」，不至于长 session 因
   网络抖动而全部历史进上下文。

存储模型不变
~~~~~~~~~~~~
agent-flow 沿用 ``Memory.compressed_summary`` 单字段（不像 fool-code 那
样把 boundary/summary 作为消息插入消息流），formatter 在每轮拼提示词时
注入。我们在写入 ``compressed_summary`` 前会把 summary 包成完整的"续接
消息"文本，formatter 看到则原样注入；旧 summary 不带 preamble 也兼容。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.runtime_core.formatter import ChatFormatter
from app.runtime_core.memory import Memory
from app.runtime_core.messages import Msg, MsgRole
from app.runtime_core.provider import OpenAICompatProvider

logger = logging.getLogger(__name__)


COMPRESSED_MARK = "compressed"


# ---------------------------------------------------------------------------
# Prompts (复刻 fool-code: fool_code/runtime/compact.py)
# ---------------------------------------------------------------------------

COMPACT_CONTINUATION_PREAMBLE = (
    "本次会话是从之前的对话延续的，之前的对话上下文已超出限制。"
    "以下摘要涵盖了对话早期的内容。\n\n"
)
COMPACT_RECENT_MESSAGES_NOTE = "最近的消息已原样保留。"
COMPACT_DIRECT_RESUME_INSTRUCTION = (
    "从上次中断的地方继续对话，不要向用户提出任何进一步的问题。"
    "直接继续——不要确认摘要，不要回顾之前的内容，也不要添加"
    "任何过渡性文字。"
)


COMPRESSION_SYS_PROMPT = (
    "重要：仅以纯文本回复，不要调用任何工具。\n\n"
    "- 不要使用任何工具调用。\n"
    "- 你已经拥有对话中所有需要的上下文信息。\n"
    "- 工具调用会被拒绝并浪费你唯一的回合——你将无法完成任务。\n"
    "- 你的整个回复必须是纯文本：先输出 <analysis> 块，再输出 <summary> 块。\n\n"
    "你是一个负责总结对话的 AI 助手。"
)


COMPRESSION_USER_PROMPT = """\
你的任务是为目前为止的对话创建一份详细的摘要，密切关注用户的明确请求和你之前的操作。
这份摘要应当全面捕获技术细节、代码模式和架构决策，这些对于在不丢失上下文的情况下继续开发工作至关重要。

在提供最终摘要之前，请将你的分析过程包裹在 <analysis> 标签中，以整理思路并确保涵盖所有必要的要点。在分析过程中：

1. 按时间顺序分析对话中的每条消息和每个部分。对于每个部分，彻底识别：
   - 用户的明确请求和意图
   - 你处理用户请求的方式
   - 关键决策、技术概念和代码模式
   - 具体细节，例如：
     - 文件名
     - 完整代码片段
     - 函数签名
     - 文件编辑
   - 你遇到的错误以及如何修复
   - 特别注意你收到的用户反馈，尤其是用户要求你以不同方式做事的情况。
2. 仔细检查技术准确性和完整性，确保每个必需的要素都被充分涵盖。

你的摘要应包含以下章节：

1. 主要请求和意图：详细捕获用户所有明确的请求和意图
2. 关键技术概念：列出讨论过的所有重要技术概念、技术栈和框架。
3. 文件和代码部分：列举检查、修改或创建的具体文件和代码部分。特别关注最近的消息，尽可能包含完整代码片段，并总结为什么这个文件的读取或编辑很重要。
4. 错误和修复：列出你遇到的所有错误以及修复方式。特别注意用户的具体反馈，尤其是用户要求你以不同方式做事的情况。
5. 问题解决：记录已解决的问题和正在进行的故障排查工作。
6. 所有用户消息：列出所有非工具结果的用户消息。这些对于理解用户的反馈和变化的意图至关重要。
7. 待处理任务：列出用户明确要求你处理的所有待完成任务。
8. 当前工作：详细描述在此摘要请求之前正在进行的确切工作，特别关注用户和助手最近的消息。尽可能包含文件名和代码片段。
9. 可选的下一步：列出与你最近工作相关的下一个步骤。重要提示：确保此步骤直接符合用户最近的明确请求以及你在此摘要请求之前正在处理的任务。

请基于目前的对话提供你的摘要，遵循上述结构并确保精确和全面。
请将分析输出在 <analysis> 标签中，将最终摘要输出在 <summary> 标签中。"""


# 旧名字保留以免有外部 import 报错。
COMPRESSION_USER_PROMPT_LEGACY = COMPRESSION_USER_PROMPT


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class CompressionConfig:
    enable: bool = True
    trigger_threshold_tokens: int = 50000
    keep_recent: int = 3
    # LLM 摘要的 max_tokens；fool-code 默认 16000，agent-flow 沿用偏保守的
    # 8000，避免极长摘要把节省下来的 context 又吃回去。
    summary_max_tokens: int = 8000
    # 单条 tool_result 进入上下文的 token 上限。超过即就地截断（豁免最近一回合）。
    # 治"大结果落在 keep_recent 保留窗口、摘要压缩够不到"的洞：某些工具一次拉
    # 数百条这种巨型结果，若正好在最近几轮，摘要压缩碰不到它，会一直占满 context。
    # 0 表示关闭截断。默认 6000 ≈ 几十条记录/一屏明细，够模型当轮分析又不至于撑爆。
    max_tool_result_tokens: int = 6000


# ---------------------------------------------------------------------------
# Token 估算 + 选取要压缩的消息（保留 tool_use/result 配对）
# ---------------------------------------------------------------------------

# 中日韩（含全角标点 / 假名 / 扩展区）字符。这些字符在主流 BPE 分词器里
# 通常 1 字 ≈ 1 token 甚至更多，绝不能按"英文 4 char ≈ 1 token"折算——否则
# 中文对话的真实 token 会被低估 4~6 倍，压缩迟迟不触发，最终把模型上下文顶爆。
_CJK_RE = re.compile(
    r"[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef\u3400-\u4dbf]"
)


def _estimate_text_tokens(text: str) -> int:
    """对单段文本做 CJK 感知的 token 估算。

    - CJK 字符按 1 token/字 计（保守略高，宁可早压缩也不要顶爆上下文）；
    - 其余字符（英文 / 代码 / ASCII 标点）沿用 4 char ≈ 1 token。
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return cjk + other // 4


def _estimate_tokens(messages: Iterable[dict]) -> int:
    """粗略的 char→token 估算（CJK 1:1，其余 4:1），避免引入额外依赖。"""
    tokens = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            tokens += _estimate_text_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    tokens += _estimate_text_tokens(part.get("text") or "")
        for tc in m.get("tool_calls") or []:
            args = (tc.get("function") or {}).get("arguments") or ""
            tokens += _estimate_text_tokens(args)
    return max(1, tokens)


def _recent_turn_cut_index(all_msgs: list[Msg], keep_recent: int) -> int | None:
    """从尾部往前数 ``keep_recent`` 个"完整逻辑回合"（一个回合 = 普通消息，或者
    一组 tool_use/tool_result 全部齐全的消息），返回切分下标 ``cut_index``：

    * ``all_msgs[:cut_index]`` 是更早的、可压缩 / 可截断的部分；
    * ``all_msgs[cut_index:]`` 是要原样保留的最近 ``keep_recent`` 个回合。

    数不够 ``keep_recent`` 个完整回合（历史太短）时返回 ``None``，表示没有可切
    分出来的较早部分。被 :func:`_collect_compressible`（摘要压缩）和
    :func:`_truncate_oversized_tool_results`（超大结果截断）共用，保证两者对
    "最近回合"的认定口径一致、不会破坏 tool_use/tool_result 配对。
    """
    if not all_msgs:
        return None

    n_keep = 0
    pending_tool_call_ids: set[str] = set()
    for i in range(len(all_msgs) - 1, -1, -1):
        msg = all_msgs[i]
        for block in msg.get_content_blocks("tool_result"):
            tid = str(block.get("id") or "")
            if tid:
                pending_tool_call_ids.add(tid)
        for block in msg.get_content_blocks("tool_use"):
            tid = str(block.get("id") or "")
            if tid in pending_tool_call_ids:
                pending_tool_call_ids.remove(tid)

        if not pending_tool_call_ids:
            n_keep += 1

        if n_keep >= keep_recent:
            return i

    return None


def _collect_compressible(memory: Memory, keep_recent: int) -> list[Msg]:
    """保留最近 ``keep_recent`` 个完整回合，更早的全部纳入摘要压缩。"""
    all_msgs = memory.get_memory(exclude_mark=COMPRESSED_MARK)
    cut_index = _recent_turn_cut_index(all_msgs, keep_recent)
    if cut_index is None:
        return []
    return all_msgs[:cut_index]


def _truncate_oversized_tool_results(
    memory: Memory,
    *,
    max_result_tokens: int,
    keep_last_turns: int = 1,
) -> bool:
    """把历史里超过 ``max_result_tokens`` 的 ``tool_result.output`` 就地截断。

    豁免最近 ``keep_last_turns`` 个完整回合——刚查回来的结果模型当轮可能正要
    用，不能截；再往前的（哪怕仍落在摘要压缩的 ``keep_recent`` 保留窗口内）超大
    结果则封顶截断，从根上堵住"大结果堆在保留窗口、谁也压不掉、整体顶爆 context"。

    只截 ``str`` 形态的 output（各类工具回的大结果多是 ``json.dumps``
    字符串，大结果几乎都在这里）；非字符串的小结构跳过。直接改 ``Msg.blocks`` 里
    的 dict——``Memory.get_memory`` 返回的是消息对象引用，改动会随 ``state_dict``
    持久化，等于"这条大结果用过一次后永久瘦身"。返回是否发生过截断。
    """
    if max_result_tokens <= 0:
        return False
    all_msgs = memory.get_memory(exclude_mark=COMPRESSED_MARK)
    cut_index = _recent_turn_cut_index(all_msgs, keep_last_turns)
    # cut_index 之前是"较早、可截断"的；None（回合不足）则全部豁免、不截。
    upper = cut_index if cut_index is not None else 0
    if upper <= 0:
        return False

    # token→char 的粗略反推：CJK 1:1、ASCII 4:1，取 ×2 折中，宁可多留一点也不过截。
    keep_chars = max(256, max_result_tokens * 2)
    changed = False
    for msg in all_msgs[:upper]:
        for block in msg.get_content_blocks("tool_result"):
            output = block.get("output")
            if not isinstance(output, str) or not output:
                continue
            tok = _estimate_text_tokens(output)
            if tok <= max_result_tokens:
                continue
            block["output"] = (
                output[:keep_chars]
                + f"\n…[超大工具结果已截断：原约 {tok} tokens，仅保留前段以节省上下文。"
                "需要完整数据请缩小查询范围或用更精确的条件重查。]"
            )
            changed = True
    return changed


# ---------------------------------------------------------------------------
# Tag 解析（<analysis> / <summary>）+ 续接消息组装
# ---------------------------------------------------------------------------

def _extract_tag_block(content: str, tag: str) -> str | None:
    start = f"<{tag}>"
    end = f"</{tag}>"
    si = content.find(start)
    if si == -1:
        return None
    after = si + len(start)
    ei = content.find(end, after)
    if ei == -1:
        return None
    return content[after:ei]


def _strip_tag_block(content: str, tag: str) -> str:
    start = f"<{tag}>"
    end = f"</{tag}>"
    si = content.find(start)
    ei = content.find(end)
    if si == -1 or ei == -1:
        return content
    return content[:si] + content[ei + len(end):]


def _collapse_blank_lines(content: str) -> str:
    result: list[str] = []
    last_blank = False
    for line in content.splitlines():
        is_blank = not line.strip()
        if is_blank and last_blank:
            continue
        result.append(line)
        last_blank = is_blank
    return "\n".join(result)


def format_compact_summary(summary: str) -> str:
    """剥掉 <analysis>，把 <summary> 里的内容提到外层，折叠空行。

    输入举例::

        <analysis>...逐条分析...</analysis>
        <summary>
        1. 主要请求和意图：...
        2. 关键技术概念：...
        ...
        </summary>

    输出::

        摘要：
        1. 主要请求和意图：...
        2. 关键技术概念：...
        ...
    """
    without_analysis = _strip_tag_block(summary, "analysis")
    content = _extract_tag_block(without_analysis, "summary")
    if content is not None:
        formatted = without_analysis.replace(
            f"<summary>{content}</summary>",
            f"摘要：\n{content.strip()}",
        )
    else:
        formatted = without_analysis
    return _collapse_blank_lines(formatted).strip()


def get_compact_continuation_message(
    summary: str,
    *,
    suppress_follow_up: bool = True,
    recent_preserved: bool = True,
) -> str:
    """把摘要拼成完整的"续接消息"文本，含 preamble + 摘要 + 续接说明。"""
    base = COMPACT_CONTINUATION_PREAMBLE + format_compact_summary(summary)
    if recent_preserved:
        base += "\n\n" + COMPACT_RECENT_MESSAGES_NOTE
    if suppress_follow_up:
        base += "\n" + COMPACT_DIRECT_RESUME_INSTRUCTION
    return base


# ---------------------------------------------------------------------------
# 多次压缩合并：旧 summary + 新 summary
# ---------------------------------------------------------------------------

def _extract_summary_highlights(summary: str) -> list[str]:
    """从已经 format 过的 summary 文本里抽取"非时间线"的列表行。"""
    lines: list[str] = []
    in_timeline = False
    for line in format_compact_summary(summary).splitlines():
        trimmed = line.rstrip()
        if not trimmed or trimmed in (
            "Summary:", "Conversation summary:", "摘要：", "对话摘要：",
        ):
            continue
        if trimmed in ("- Key timeline:", "- 关键时间线："):
            in_timeline = True
            continue
        if in_timeline:
            continue
        lines.append(trimmed)
    return lines


def _extract_summary_timeline(summary: str) -> list[str]:
    lines: list[str] = []
    in_timeline = False
    for line in format_compact_summary(summary).splitlines():
        trimmed = line.rstrip()
        if trimmed in ("- Key timeline:", "- 关键时间线："):
            in_timeline = True
            continue
        if not in_timeline:
            continue
        if not trimmed:
            break
        lines.append(trimmed)
    return lines


def _merge_compact_summaries(existing: str | None, new_summary: str) -> str:
    """把上一次压缩 + 本次新压缩 的摘要合成一段，避免反复压缩丢早期上下文。"""
    if not existing:
        return new_summary

    prev_highlights = _extract_summary_highlights(existing)
    new_formatted = format_compact_summary(new_summary)
    new_highlights = _extract_summary_highlights(new_formatted)
    new_timeline = _extract_summary_timeline(new_formatted)

    lines = ["<summary>", "对话摘要："]
    if prev_highlights:
        lines.append("- 之前压缩的上下文：")
        lines.extend(f"  {h}" for h in prev_highlights)
    if new_highlights:
        lines.append("- 新压缩的上下文：")
        lines.extend(f"  {h}" for h in new_highlights)
    if new_timeline:
        lines.append("- 关键时间线：")
        lines.extend(f"  {t}" for t in new_timeline)
    lines.append("</summary>")
    return "\n".join(lines)


def _existing_summary_from_memory(memory: Memory) -> str | None:
    """从 memory 里取出之前一次写入的"原始 summary"（去掉续接 preamble）。"""
    text = memory.compressed_summary
    if not text:
        return None
    if text.startswith(COMPACT_CONTINUATION_PREAMBLE):
        rest = text[len(COMPACT_CONTINUATION_PREAMBLE):]
        for sentinel in (
            f"\n\n{COMPACT_RECENT_MESSAGES_NOTE}",
            f"\n{COMPACT_DIRECT_RESUME_INSTRUCTION}",
        ):
            idx = rest.find(sentinel)
            if idx != -1:
                rest = rest[:idx]
        return rest.strip()
    return text.strip()


# ---------------------------------------------------------------------------
# 规则法兜底（LLM 失败时退化）
# ---------------------------------------------------------------------------

_INTERESTING_EXTS = frozenset(("rs", "ts", "tsx", "js", "json", "md", "py", "toml"))
_PENDING_KEYWORDS = ("todo", "next", "pending", "follow up", "remaining", "待办", "下一步")
_FILE_TOKEN_RE = re.compile(r"[\s,，。；;:'\"`()\[\]<>]")


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[:n] + "…"


def _extract_file_candidates(content: str) -> list[str]:
    result: list[str] = []
    for token in _FILE_TOKEN_RE.split(content):
        candidate = token.strip(",.;:)('\"` ")
        if not candidate or "/" not in candidate:
            continue
        ext = candidate.rsplit(".", 1)[-1].lower() if "." in candidate else ""
        if ext in _INTERESTING_EXTS:
            result.append(candidate)
    return result


def _msg_first_text(msg: Msg) -> str | None:
    for b in msg.blocks:
        if b.get("type") == "text":
            t = (b.get("text") or "").strip()
            if t:
                return t
    return None


def _rule_based_summary(messages: list[Msg]) -> str:
    """LLM 失败时的最后兜底——纯统计 + 关键文件 + 最近用户请求。

    输出形式仍然套 ``<summary>`` 标签，让 ``format_compact_summary`` 能直接处理。
    """
    role_counts = {"user": 0, "assistant": 0, "tool": 0, "system": 0}
    tool_names: list[str] = []
    file_candidates: set[str] = set()

    for m in messages:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        if role == "system":
            # 系统/工具结果通常以 SYSTEM 角色携带 tool_result block
            if m.get_content_blocks("tool_result"):
                role_counts["tool"] += 1
            else:
                role_counts["system"] += 1
        elif role in role_counts:
            role_counts[role] += 1
        for b in m.blocks:
            t = b.get("type")
            if t == "tool_use" and b.get("name"):
                tool_names.append(str(b["name"]))
            elif t == "tool_result" and b.get("tool_name"):
                tool_names.append(str(b["tool_name"]))
            for field in ("text", "input", "output"):
                val = b.get(field)
                if isinstance(val, str) and val:
                    file_candidates.update(_extract_file_candidates(val))

    recent_user: list[str] = []
    for m in reversed(messages):
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        if role != "user":
            continue
        text = _msg_first_text(m)
        if text:
            recent_user.append(_truncate(text, 160))
        if len(recent_user) >= 3:
            break
    recent_user.reverse()

    pending: list[str] = []
    for m in reversed(messages):
        text = _msg_first_text(m)
        if not text:
            continue
        low = text.lower()
        if any(kw in low for kw in _PENDING_KEYWORDS):
            pending.append(_truncate(text, 160))
        if len(pending) >= 3:
            break
    pending.reverse()

    current_work = None
    for m in reversed(messages):
        text = _msg_first_text(m)
        if text:
            current_work = _truncate(text, 200)
            break

    lines = ["<summary>", "对话摘要："]
    lines.append(
        f"- 范围：已压缩 {len(messages)} 条历史消息 "
        f"(用户={role_counts['user']}, 助手={role_counts['assistant']}, "
        f"工具={role_counts['tool']})。"
    )
    if tool_names:
        unique = sorted(set(tool_names))
        lines.append(f"- 涉及工具：{', '.join(unique)}。")
    if recent_user:
        lines.append("- 最近的用户请求：")
        lines.extend(f"  - {r}" for r in recent_user)
    if pending:
        lines.append("- 待处理工作：")
        lines.extend(f"  - {p}" for p in pending)
    if file_candidates:
        keys = sorted(file_candidates)[:8]
        lines.append(f"- 关键文件引用：{', '.join(keys)}。")
    if current_work:
        lines.append(f"- 当前工作：{current_work}")
    lines.append("</summary>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

async def maybe_compress(
    *,
    memory: Memory,
    formatter: ChatFormatter,
    provider: OpenAICompatProvider,
    config: CompressionConfig,
    observed_tokens: int | None = None,
) -> bool:
    """If history exceeds threshold, summarise the head and mark as compressed.

    ``observed_tokens``：调用方（runtime）传入的**最近一次 LLM 调用真实
    prompt token 数**（provider usage 回报值）。字符估算对工具 schema、多模态
    内容、供应商分词差异一无所知，可能系统性低估；真实值兜底后触发判断取
    ``max(估算, 真实)``。注意真实值反映的是"上一次调用时"的上下文（其后新追加
    的 tool_result 不在内），所以两者互为补充，谁大听谁的。

    Returns ``True`` if compression actually happened.
    """
    if not config.enable:
        return False

    observed = int(observed_tokens or 0)

    # 快速短路：ReAct loop 每一轮 reasoning 前都会调一次 maybe_compress；
    # 如果距离上次调用 memory 没增长且当时没触发压缩，就没必要再
    # _collect_compressible + formatter.format + 估算 token —— 这些虽然
    # 是纯 CPU，但在长 session 上叠加起来也会拖慢"上一个 tool 已返回、下
    # 一个 LLM 调用迟迟不发"的体感。用 memory 当前长度 + 已压缩消息数
    # 作为低开销 cache key（任意一边变了就重新评估）。
    # observed 超阈值时跳过短路：真实用量已经说明必须压，不能被旧缓存挡住。
    cache_key = (len(memory), len(memory.get_memory(exclude_mark=COMPRESSED_MARK)))
    cache_slot: dict[str, Any] = getattr(memory, "_compress_check_cache", None) or {}
    if (
        observed <= config.trigger_threshold_tokens
        and cache_slot.get("key") == cache_key
        and cache_slot.get("under_threshold")
    ):
        return False

    # P0-1：触发判断基于"整个未压缩上下文"（含已有摘要），而不是只看 keep_recent
    # 之外的"可压缩部分"。否则大结果都堆在最近几轮时，可压部分很小、迟迟不触发，
    # 整体却已顶爆模型 context（线上 cf395752 即如此：涨到 131K/135K 才 400）。
    def _ctx_tokens() -> int:
        return _estimate_tokens(
            formatter.format(
                memory.get_memory(exclude_mark=COMPRESSED_MARK),
                sys_prompt=COMPRESSION_SYS_PROMPT,
                compressed_summary=memory.compressed_summary,
            )
        )

    estimated_tokens = _ctx_tokens()
    total_tokens = max(estimated_tokens, observed)
    if total_tokens <= config.trigger_threshold_tokens:
        memory._compress_check_cache = {  # type: ignore[attr-defined]
            "key": cache_key, "under_threshold": True,
        }
        return False

    # 整体已超阈值 → 先摘要压缩"可压缩部分"（keep_recent 之外的较早回合）。
    to_compress = _collect_compressible(memory, config.keep_recent)
    if not to_compress:
        # 没有更早消息可摘要：大结果全堆在最近 keep_recent 个回合里。直接走 P0-2
        # 兜底截断（保留最近一回合，避免误伤当前追问所需的最新查询结果），不调
        # 摘要 LLM。
        changed = _truncate_oversized_tool_results(
            memory,
            max_result_tokens=config.max_tool_result_tokens,
            keep_last_turns=1,
        )
        memory._compress_check_cache = None  # type: ignore[attr-defined]
        if not changed:
            logger.warning(
                "[compress] over threshold (~%d tokens) but nothing compressible/"
                "truncatable: 最近 keep_recent=%d 个回合已占满上下文，"
                "考虑调小 max_records 或 keep_recent",
                total_tokens, config.keep_recent,
            )
        return changed

    logger.info(
        "[compress] triggered: total ~%d tokens, compressing %d earlier msgs",
        total_tokens,
        len(to_compress),
    )

    payload = formatter.format(
        list(to_compress) + [Msg.user(COMPRESSION_USER_PROMPT)],
        sys_prompt=COMPRESSION_SYS_PROMPT,
    )

    raw_summary: str | None = None
    used_fallback = False
    try:
        raw_summary = await provider.simple_chat(
            payload, max_tokens=config.summary_max_tokens
        )
    except Exception:
        logger.exception("[compress] LLM summary generation failed, falling back to rule-based")
        used_fallback = True

    if not (raw_summary and raw_summary.strip()):
        if not used_fallback:
            logger.warning("[compress] LLM returned empty, falling back to rule-based")
        used_fallback = True
        raw_summary = _rule_based_summary(to_compress)

    new_summary_text = raw_summary.strip()

    existing_raw = _existing_summary_from_memory(memory)
    merged = (
        _merge_compact_summaries(existing_raw, new_summary_text)
        if existing_raw
        else new_summary_text
    )

    continuation = get_compact_continuation_message(
        merged,
        suppress_follow_up=True,
        recent_preserved=True,
    )

    memory.update_compressed_summary(continuation)
    memory.mark_messages([m.id for m in to_compress], COMPRESSED_MARK)

    # P0-2 兜底：摘要压缩后若整体仍超阈值，说明 keep_recent 保留窗口里堆着大结果
    # （摘要压缩够不到它们，典型如同一轮里连续多次大查询）。把窗口内、最近一回合
    # 之外的超大 tool_result 就地截断，保留最近一回合，避免误伤用户当前正基于其
    # 追问的最新查询结果。
    if _ctx_tokens() > config.trigger_threshold_tokens:
        _truncate_oversized_tool_results(
            memory,
            max_result_tokens=config.max_tool_result_tokens,
            keep_last_turns=1,
        )

    # 压缩完后失效缓存：下一轮再 maybe_compress 时按新的 memory 状态重新评估
    memory._compress_check_cache = None  # type: ignore[attr-defined]
    logger.info(
        "[compress] done: %d msgs compressed, summary_len=%d chars, fallback=%s",
        len(to_compress),
        len(continuation),
        used_fallback,
    )
    return True


# Suppress an unused-import warning in callers.
_ = MsgRole

__all__ = [
    "COMPACT_CONTINUATION_PREAMBLE",
    "COMPACT_DIRECT_RESUME_INSTRUCTION",
    "COMPACT_RECENT_MESSAGES_NOTE",
    "COMPRESSED_MARK",
    "COMPRESSION_SYS_PROMPT",
    "COMPRESSION_USER_PROMPT",
    "CompressionConfig",
    "format_compact_summary",
    "get_compact_continuation_message",
    "maybe_compress",
]
