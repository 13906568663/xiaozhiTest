"""验证 prompt / template 渲染层遇到 artifact ref 或大对象时走「摘要」而非展开。

这是 P0 修复的核心断言：即使下游节点的 ``${context.stepX.fibers}`` 占位符指向
一个 ref list，最终注入到 system / user prompt 的也只是 ``<artifact-list ...>``
之类的几十字节摘要，不会把上游 N 百 KB 的 raw JSON 灌进 LLM 上下文。
"""

from __future__ import annotations

from app.workflow.runtime.prompt import _format_field_value, _format_node_output
from app.workflow.runtime.template import resolve_value_template
from app.workflow.services.session_assets import (
    is_artifact_ref,
    is_artifact_ref_list,
    summarize_artifact_value,
)


def test_summarize_artifact_value_for_ref_dict() -> None:
    assert is_artifact_ref({"__artifact": "abc-1"})
    text = summarize_artifact_value({"__artifact": "abc-1", "path": "$.data"})
    assert text is not None
    assert "abc-1" in text
    assert "$.data" in text


def test_summarize_artifact_value_for_ref_list() -> None:
    refs = [{"__artifact": f"id-{i}", "path": "$.data"} for i in range(7)]
    assert is_artifact_ref_list(refs)
    text = summarize_artifact_value(refs)
    assert text is not None
    assert "artifact-list" in text
    assert "id-0" in text and "id-1" in text
    assert "共 7 个" in text


def test_resolve_value_template_summarizes_artifact_ref() -> None:
    template = "fibers={fibers}".format(fibers="${context.step3.fibers}")
    big_refs = [{"__artifact": f"u-{i}", "path": "$.data"} for i in range(200)]
    context = {"step3": {"fibers": big_refs}}
    out = resolve_value_template(template, context=context)
    assert isinstance(out, str)
    assert "artifact-list" in out
    # 关键断言：不应包含 raw JSON 把 prompt 撑爆
    assert "__artifact" not in out
    assert len(out) < 500  # 200 个 ref 的摘要绝对不该超过 500 字符


def test_resolve_value_template_large_dict_falls_back_to_summary() -> None:
    template = "ctx=${context.huge}"
    big = {f"k{i}": "x" * 100 for i in range(200)}
    out = resolve_value_template(template, context={"huge": big})
    assert isinstance(out, str)
    assert "large-dict" in out
    assert "k0" in out  # 摘要里会提示前几个 key 名


def test_format_field_value_for_ref_list_in_node_output() -> None:
    refs = [{"__artifact": "a-1"}, {"__artifact": "a-2"}]
    out = _format_field_value(refs, budget=2000)
    assert "artifact-list" in out


def test_format_node_output_renders_summary_not_raw_for_refs() -> None:
    refs = [{"__artifact": f"x-{i}"} for i in range(50)]
    node_output = {"fibers": refs, "fiber_count": 1234}
    text = _format_node_output(node_output, max_length=4000)
    assert "**fibers:**" in text
    assert "artifact-list" in text
    assert "1234" in text
