"""compression P0 修复回归测试。

覆盖两条线上 cf395752 暴露的结构性缺陷：

* **P0-1**：``maybe_compress`` 的触发判断要基于"整个未压缩上下文"，而不是只看
  keep_recent 之外的"可压缩部分"——否则大结果都堆在最近几轮时迟迟不触发，整体
  却已顶爆模型 context。
* **P0-2**：keep_recent 保留窗口里的超大 ``tool_result`` 摘要压缩够不到，需要在
  "压缩后整体仍超阈值"时就地截断（保留最近一回合，避免误伤当前追问所需结果）。

测试不拉真实 LLM：``maybe_compress`` 的摘要生成用 fake provider 顶替。
"""

from __future__ import annotations

import asyncio

from app.runtime_core.compression import (
    COMPRESSED_MARK,
    CompressionConfig,
    _collect_compressible,
    _recent_turn_cut_index,
    _truncate_oversized_tool_results,
    maybe_compress,
)
from app.runtime_core.formatter import ChatFormatter
from app.runtime_core.memory import Memory
from app.runtime_core.messages import Msg, tool_result_block, tool_use_block


# ASCII 字符按 4:1 估算 token，方便精确控制规模：n token ≈ 4n 个 'x'。
def _big(n_tokens: int) -> str:
    return "x" * (n_tokens * 4)


class _FakeProvider:
    """只实现 maybe_compress 用到的 ``simple_chat``，返回固定 <summary> 文本。"""

    def __init__(self, reply: str = "<analysis>a</analysis><summary>\n- 要点A\n- 要点B\n</summary>") -> None:
        self.reply = reply
        self.calls = 0

    async def simple_chat(self, payload, max_tokens=None, **_):  # noqa: ANN001
        self.calls += 1
        return self.reply


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _recent_turn_cut_index：回合边界（压缩 / 截断共用，配对不能破）
# ---------------------------------------------------------------------------


def test_recent_turn_cut_index_plain_messages() -> None:
    msgs = [
        Msg.user("a"), Msg.assistant("b"), Msg.user("c"),
        Msg.assistant("d"), Msg.user("e"),
    ]
    # 纯文本：每条算一个回合点，keep_recent=3 → 保留最后 3 条
    assert _recent_turn_cut_index(msgs, 3) == 2
    # 回合不足 → None（没有可切出来的较早部分）
    assert _recent_turn_cut_index(msgs, 10) is None
    assert _recent_turn_cut_index([], 1) is None


def test_recent_turn_cut_index_keeps_tool_pair_intact() -> None:
    msgs = [
        Msg.user("q"),
        Msg.assistant([tool_use_block("t1", "tool", {})]),
        Msg.tool_results([tool_result_block("t1", "tool", "out")]),
        Msg.assistant("final"),
    ]
    # keep_recent=1 → 只保留最后的纯文本回合
    assert _recent_turn_cut_index(msgs, 1) == 3
    # keep_recent=2 → tool_use+tool_result 算一个完整回合，整组一起保留
    assert _recent_turn_cut_index(msgs, 2) == 1
    # 同一切分喂给 _collect_compressible：cut=1 → 可压只有最前面的 user
    assert _collect_compressible(_mem(msgs), 2) == msgs[:1]


def _mem(msgs) -> Memory:
    m = Memory()
    m.add_messages(msgs)
    return m


# ---------------------------------------------------------------------------
# _truncate_oversized_tool_results：截早、留近、不碰小/非字符串
# ---------------------------------------------------------------------------


def test_truncate_oversized_truncates_old_keeps_recent() -> None:
    big = _big(1000)
    msgs = [
        Msg.user("q1"),
        Msg.assistant([tool_use_block("t1", "tool", {})]),
        Msg.tool_results([tool_result_block("t1", "tool", big)]),   # idx2 较早
        Msg.assistant("mid"),
        Msg.assistant([tool_use_block("t2", "tool", {})]),
        Msg.tool_results([tool_result_block("t2", "tool", big)]),   # idx5 最近
    ]
    mem = _mem(msgs)
    changed = _truncate_oversized_tool_results(
        mem, max_result_tokens=100, keep_last_turns=1,
    )
    assert changed is True
    all_m = mem.get_memory()
    out_old = all_m[2].get_content_blocks("tool_result")[0]["output"]
    out_recent = all_m[5].get_content_blocks("tool_result")[0]["output"]
    assert "已截断" in out_old and len(out_old) < len(big)   # 较早被截
    assert out_recent == big                                  # 最近一回合豁免


def test_truncate_skips_small_and_nonstr_and_recent() -> None:
    msgs = [
        Msg.user("q1"),
        Msg.assistant([tool_use_block("t1", "tool", {})]),
        Msg.tool_results([tool_result_block("t1", "tool", _big(10))]),     # 小，不截
        Msg.assistant("mid"),
        Msg.assistant([tool_use_block("t2", "tool", {})]),
        Msg.tool_results([tool_result_block("t2", "tool", {"k": "v"})]),   # 非字符串 + 最近
    ]
    mem = _mem(msgs)
    changed = _truncate_oversized_tool_results(
        mem, max_result_tokens=100, keep_last_turns=1,
    )
    assert changed is False


# ---------------------------------------------------------------------------
# maybe_compress：P0-1 整体触发 / 不超不压 / P0-2 兜底截断
# ---------------------------------------------------------------------------


def test_maybe_compress_triggers_on_total_context() -> None:
    async def go() -> None:
        mem = Memory()
        for i in range(6):
            mem.add_message(Msg.user(_big(1000)) if i % 2 == 0 else Msg.assistant(_big(1000)))
        cfg = CompressionConfig(
            trigger_threshold_tokens=2000, keep_recent=2, max_tool_result_tokens=10**9,
        )
        prov = _FakeProvider()
        result = await maybe_compress(
            memory=mem, formatter=ChatFormatter(), provider=prov, config=cfg,
        )
        assert result is True
        assert prov.calls == 1
        assert mem.compressed_summary is not None
        assert "要点A" in mem.compressed_summary
        # keep_recent=2 → 较早 4 条被打上 compressed 标记，不再进下一轮
        assert len(mem.get_memory(exclude_mark=COMPRESSED_MARK)) < 6

    _run(go())


def test_maybe_compress_skips_under_threshold() -> None:
    async def go() -> None:
        mem = Memory()
        mem.add_message(Msg.user(_big(100)))
        cfg = CompressionConfig(trigger_threshold_tokens=5000, keep_recent=2)
        prov = _FakeProvider()
        result = await maybe_compress(
            memory=mem, formatter=ChatFormatter(), provider=prov, config=cfg,
        )
        assert result is False
        assert prov.calls == 0
        assert mem.compressed_summary is None

    _run(go())


def test_maybe_compress_observed_tokens_overrides_low_estimate() -> None:
    """字符估算远低于阈值、但真实 usage 超阈值 → 仍要触发压缩。

    真实场景：工具 schema / 多模态内容不在消息字符里，字符估算系统性低估；
    provider 回报的 prompt_tokens 才是权威。
    """

    async def go() -> None:
        mem = Memory()
        # 6 条短消息：字符估算约几十 token，远低于 2000 阈值
        for i in range(6):
            mem.add_message(
                Msg.user(f"短消息{i}") if i % 2 == 0 else Msg.assistant(f"回复{i}")
            )
        cfg = CompressionConfig(
            trigger_threshold_tokens=2000, keep_recent=2, max_tool_result_tokens=10**9,
        )
        prov = _FakeProvider()

        # 不带 observed → 不触发
        result = await maybe_compress(
            memory=mem, formatter=ChatFormatter(), provider=prov, config=cfg,
        )
        assert result is False and prov.calls == 0

        # 带上超阈值的真实 usage → 触发压缩；且不被上一次的 under_threshold
        # 短路缓存挡住（memory 未变、缓存命中，但 observed 必须绕过缓存）
        result = await maybe_compress(
            memory=mem, formatter=ChatFormatter(), provider=prov, config=cfg,
            observed_tokens=5000,
        )
        assert result is True
        assert prov.calls == 1
        assert mem.compressed_summary is not None

    _run(go())


def test_maybe_compress_observed_under_threshold_no_trigger() -> None:
    """真实 usage 低于阈值且估算也低 → 不触发（observed 不应造成误触发）。"""

    async def go() -> None:
        mem = Memory()
        mem.add_message(Msg.user(_big(100)))
        cfg = CompressionConfig(trigger_threshold_tokens=5000, keep_recent=2)
        prov = _FakeProvider()
        result = await maybe_compress(
            memory=mem, formatter=ChatFormatter(), provider=prov, config=cfg,
            observed_tokens=3000,
        )
        assert result is False
        assert prov.calls == 0

    _run(go())


def test_maybe_compress_truncates_oversized_window_when_nothing_compressible() -> None:
    """大结果全堆在最近几轮、没有更早消息可摘要 → 兜底截断窗口内较早的大结果。"""

    async def go() -> None:
        big = _big(1000)
        mem = Memory()
        mem.add_message(Msg.user("q1"))
        mem.add_message(Msg.assistant([tool_use_block("t1", "tool", {})]))
        mem.add_message(Msg.tool_results([tool_result_block("t1", "tool", big)]))  # 较早
        mem.add_message(Msg.assistant("mid"))
        mem.add_message(Msg.assistant([tool_use_block("t2", "tool", {})]))
        mem.add_message(Msg.tool_results([tool_result_block("t2", "tool", big)]))  # 最近
        # keep_recent 调大 → 回合不足，没有可摘要的较早消息（to_compress 为空）
        cfg = CompressionConfig(
            trigger_threshold_tokens=500, keep_recent=10, max_tool_result_tokens=100,
        )
        prov = _FakeProvider()
        result = await maybe_compress(
            memory=mem, formatter=ChatFormatter(), provider=prov, config=cfg,
        )
        assert result is True       # 发生了截断
        assert prov.calls == 0      # 没调摘要 LLM
        assert mem.compressed_summary is None
        all_m = mem.get_memory()
        out_old = all_m[2].get_content_blocks("tool_result")[0]["output"]
        out_recent = all_m[5].get_content_blocks("tool_result")[0]["output"]
        assert "已截断" in out_old   # 较早大结果被截
        assert out_recent == big     # 最近一回合豁免

    _run(go())
