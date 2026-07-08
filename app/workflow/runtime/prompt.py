"""节点会话的 Prompt 构建。

包含系统提示词、回合 user message、事件引导和恢复消息的生成逻辑。
"""

from __future__ import annotations

import json
from typing import Any

from app.runtime_core.messages import Msg

from app.workflow.runtime.helpers import snapshot_json
from app.workflow.runtime.template import resolve_value_template
from app.workflow.schemas import SessionPromptConfig, TaskNodeDefinition

# 单字段内嵌 JSON 体积上限。超过此值在「前序节点输出」分段中只显示摘要，
# 不展开原始内容；artifact ref / ref-list 任何情况下都走摘要（即使 raw 形态
# 单条很小，flatten 后可能上百 KB）。
MAX_FIELD_INLINE_BYTES = 1500


def resolve_node_prompts(
    node: TaskNodeDefinition,
    context: dict[str, Any],
) -> TaskNodeDefinition:
    """对节点提示词字段中的 ${context.xxx.yyy} 模板变量做解析替换。

    返回一个浅拷贝的 node，其中 prompt 和 session_prompt_config 中的
    文本字段已经过模板解析（支持引用上游节点输出等）。
    """
    resolved_prompt = resolve_value_template(
        node.prompt, context=context, node=node,
    )
    resolved_config = node.session_prompt_config
    if resolved_config is not None:
        resolved_config = SessionPromptConfig(
            role=resolve_value_template(
                resolved_config.role, context=context, node=node,
            ),
            objective=resolve_value_template(
                resolved_config.objective, context=context, node=node,
            ),
            rules=[
                resolve_value_template(r, context=context, node=node)
                for r in resolved_config.rules
            ],
            success_criteria=resolve_value_template(
                resolved_config.success_criteria, context=context, node=node,
            ),
            resume_instruction=resolve_value_template(
                resolved_config.resume_instruction, context=context, node=node,
            ),
            exception_instruction=resolve_value_template(
                resolved_config.exception_instruction, context=context, node=node,
            ),
            output_instruction=resolve_value_template(
                resolved_config.output_instruction, context=context, node=node,
            ),
        )
    return node.model_copy(update={
        "prompt": resolved_prompt,
        "session_prompt_config": resolved_config,
    })


def build_session_system_prompt(
    node: TaskNodeDefinition,
    *,
    knowledge_context: str | None = None,
) -> str:
    """拼接业务提示词和运行时控制提示词。"""
    business_prompt = build_session_instruction_content(node)
    if knowledge_context:
        business_prompt += f"\n\n[知识库参考]\n{knowledge_context}"

    output_hint = _build_output_result_hint(node)

    control_prompt = (
            "===== WORKFLOW CONTROL PROTOCOL (HARD REQUIREMENT) ====="
            "\nYou are running a resumable workflow node session."
            "\nYou may call the equipped MCP and HTTP function tools multiple times."
            "\n\n!!! BATCH-FIRST RULE (HARD, 直接影响整轮耗时) !!!"
            "\n当你需要对一组**同类**对象做同样的查询/操作（例如 N 个对象"
            "查明细、N 个工单查状态、N 个文件读取），**必须在同一个 assistant"
            " 回合内一次性发出全部 N 个 tool_call**（OpenAI parallel_tool_calls"
            " 协议本框架已默认开启）。"
            "\n- 同类查询串行（调一个 → 等结果 → 再调下一个）是 ANTI-PATTERN：每多"
            "一轮就多一次完整的 LLM round-trip，9 个串行 = 9 倍延迟。"
            "\n- 例外（必须满足才允许串行）：调用之间存在数据依赖，即 A 的结果直接"
            "决定 B 的参数；这种情况主动把依赖关系在文本里说明，再发依赖调用。"
            "\n- 上游节点已经给你 N 个标识符（id / code / 名称数组）时，**直接**一次"
            "性发 N 个 tool_call，不要先"
            "「让我先查第一个看看格式」——格式是 schema 决定的，不是数据。"
            "\n\n!!! ABSOLUTE RULE !!!"
            "\nThe LAST tool call you make in EVERY turn MUST be `generate_response`."
            "\nThere is NO exception:"
            "\n- If you have an answer for the user → `generate_response(action=\"complete\", result={...})`"
            "\n- If you need the user to confirm / approve / pick an option → "
            "`generate_response(action=\"wait_callback\", result={\"prompt\": \"<what you want the user to confirm>\", ...}, instance_id=\"<unique id>\", timeout_seconds=600)`"
            "\n- If a future timer should wake the node → `generate_response(action=\"wait_timer\", wake_at=\"<ISO8601>\")`"
            "\n- If the task cannot be completed → `generate_response(action=\"fail\", error_message=\"...\")`"
            "\n\nA turn that ends with a plain assistant text and no "
            "`generate_response` call is malformed. If this node has a structured "
            "Output Instruction below, plain-text endings are treated as FAIL "
            "(not auto-complete). Other nodes may still be best-effort wrapped. "
            "Always emit `generate_response` explicitly."
            "\n\nGOOD example (asking user to confirm):"
            "\n  → call `generate_response` with arguments:"
            "\n    {\"action\": \"wait_callback\","
            "\n     \"result\": {\"prompt\": \"已查到 3 条匹配日志，是否继续推进？\","
            "\n                 \"items\": [...]},"
            "\n     \"instance_id\": \"node-6-await-user-1\","
            "\n     \"timeout_seconds\": 600}"
            "\nBAD example (structured nodes → FAIL; others → warning auto-wrap):"
            "\n  → assistant text: \"已查到 3 条日志，请确认是否继续？\""
            "\n  → no tool call at all  ← THIS IS WRONG"
            "\n\n----- Allowed control actions -----"
            "\n- complete: the node has finished successfully"
            "\n- wait_callback: suspend the node until an external callback arrives"
            "\n- wait_timer: suspend the node until a future timestamp"
            "\n- fail: terminate the node as failed"
            "\nWhen action=complete, you MUST put your structured output into the "
            "`result` field — this is what downstream nodes will receive as input. "
            "Follow the Output Instruction above to decide the content and format."
            f"{output_hint}"
            "\nUse `state_patch` to persist node-local business state for future turns."
            "\nUse `sleep_checkpoint` to persist waiting context such as sleep_id, "
            "target time, expected event, and wakeup result."
            "\nUse `compensation_config` to persist the latest compensation strategy "
            "and execution outcome."
            "\nPut durable business conclusions into structured fields instead of "
            "hidden reasoning."
            "\nWhen waiting for a callback, provide `instance_id` and `timeout_seconds`."
            "\nWhen waiting for a timer, provide `wake_at` in ISO-8601 format with timezone."
            "\nYour structured result should make it possible to reconstruct:"
            "\n- messages"
            "\n- runtime_state"
            "\n- sleep_checkpoint"
            "\n- compensation_config"
        )
    return f"{business_prompt}\n\n{control_prompt}"


def _build_output_result_hint(node: TaskNodeDefinition) -> str:
    """当节点配置了 output_instruction 时，生成额外提示引导 Agent 将输出放入 result。

    同时讲清 artifact 引用协议（``{"__artifact": "<id>", "path"?: "$.a.b"}``）
    的使用规则。stub JSON 里**不再**重复嵌这段说明（避免每条大返回多吃 ~300 token），
    全部集中在系统提示里讲一次。
    """
    config = node.session_prompt_config
    if config is None:
        return ""
    instruction = config.output_instruction.strip()
    if not instruction:
        return ""
    return (
        "\n\n!!! STRUCTURED OUTPUT (MANDATORY) !!!"
        "\nThe `result` field is the ONLY channel to pass data to downstream nodes."
        "\nYour LAST action MUST be: generate_response(action=\"complete\", result={...})"
        "\n- Put ALL deliverables inside `result` exactly as Output Instruction specifies."
        "\n- Do NOT end with plain assistant text, summaries, or questions to the user."
        "\n\n# Artifact reference protocol — DECIDE IN 1 STEP, DO NOT DELIBERATE"
        "\nLook at each tool_result you received this turn and apply this single rule:"
        "\n  • If the tool_result IS a stub object `{\"artifact_id\": \"<uuid>\","
        " \"preview\": ..., \"truncated\": true, ...}`"
        "\n      → put `{\"__artifact\": \"<that exact uuid>\", \"path\": \"$.data...\"}`"
        " (or whichever path your output_instruction wants) into result."
        "\n  • Else (tool_result is the raw payload)"
        "\n      → put the raw value (or the extracted subset) directly into result."
        "\nThat's it. No need to estimate sizes, no need to imagine the missing branch."
        " The presence of an `artifact_id` field in tool_result IS the signal."
        "\n\nPath syntax (restricted JSONPath):"
        "\n  $              entire payload"
        "\n  $.a.b          dot drill-down"
        "\n  $.list[0]      index into list"
        "\n  $.list[*]      project each element"
        "\n  $.dict.*       project each value"
        "\n  $.list[*].NAME list[dict] → list of NAME field"
        "\nMultiple ref objects in a list, e.g."
        " `[{\"__artifact\":\"<uuid-A>\"},{\"__artifact\":\"<uuid-B>\"}]`,"
        " are auto-fetched and flattened by the engine."
        "\n\n# One rule about the uuid value"
        "\nThe string inside `__artifact` must come from a tool_result's"
        " `artifact_id` field in this same session. Examples like"
        " `<paste-uuid-here>` or `step2_batch1_artifact` are placeholders, NOT"
        " valid ids — never literally copy a placeholder string."
    )


def build_session_instruction_content(node: TaskNodeDefinition) -> str:
    """把节点配置里的 role/objective/rules 等字段渲染成可读 prompt。"""
    config = node.session_prompt_config
    sections: list[str] = []

    if config is not None:
        role = config.role.strip()
        if role:
            sections.append(f"Role:\n{role}")

        objective = config.objective.strip()
        if objective:
            sections.append(f"Objective:\n{objective}")

        rules = [item.strip() for item in config.rules if item and item.strip()]
        if rules:
            sections.append("Rules:\n" + "\n".join(f"- {rule}" for rule in rules))

        success_criteria = config.success_criteria.strip()
        if success_criteria:
            sections.append(f"Success Criteria:\n{success_criteria}")

        output_instruction = config.output_instruction.strip()
        if output_instruction:
            sections.append(f"Output Instruction:\n{output_instruction}")

    legacy_prompt = str(node.prompt or "").strip()
    if legacy_prompt:
        if sections:
            sections.append(f"Additional Node Prompt:\n{legacy_prompt}")
        else:
            sections.append(legacy_prompt)

    if not sections:
        return "You are a workflow execution agent."

    return "\n\n".join(sections)


def _format_node_output(output: dict[str, Any], max_length: int = 6000) -> str:
    """将单个节点的输出格式化为 LLM 可读的文本。

    对于纯文本值直接展开（避免 JSON 转义吞掉换行），
    对于结构化值仍用缩进 JSON 保持可读性。

    artifact ref / ref-list / 大对象会被替换成摘要文本，确保下游节点
    不会因为「上游产物体积大」而把 system / user message 撑爆。LLM 仍能
    通过 artifact_id 在 Python handler 里解析出 raw 数据，但不会把它塞进 token。
    """
    if len(output) == 1:
        only_key = next(iter(output))
        only_val = output[only_key]
        if isinstance(only_val, str) and len(only_val) > 50:
            text = only_val
            if len(text) > max_length:
                text = text[:max_length] + "\n... (已截断)"
            return f"**{only_key}:**\n\n{text}"

    sections: list[str] = []
    per_field_budget = max_length // max(len(output), 1)
    for key, val in output.items():
        sections.append(f"**{key}:**\n{_format_field_value(val, per_field_budget)}")
    return "\n\n".join(sections)


def _format_field_value(val: Any, budget: int) -> str:
    """渲染单个字段的值；artifact 走摘要，大对象走截断。"""
    # 延迟导入：session_assets 在模块顶层会经包 __init__ 反向依赖到本模块，
    # 顶层 import 会形成循环导入。放到函数内按需导入即可打断环。
    from app.workflow.services.session_assets import (
        collect_artifact_summary,
        is_artifact_ref,
        is_artifact_ref_list,
        summarize_artifact_value,
    )

    # 1) artifact 直接走摘要
    if is_artifact_ref(val) or is_artifact_ref_list(val):
        return summarize_artifact_value(val) or ""
    # 2) 纯字符串：截断到 budget
    if isinstance(val, str):
        if len(val) > budget:
            return val[:budget] + "\n... (已截断)"
        return val
    # 3) list[str]：列点显示
    if isinstance(val, list) and val and all(isinstance(i, str) for i in val):
        items = "\n".join(f"- {item}" for item in val[:200])
        more = f"\n... 另有 {len(val) - 200} 项" if len(val) > 200 else ""
        return items + more
    # 4) 含 artifact 嵌套的复合对象：摘要 + 字段名提示
    artifact_summary = collect_artifact_summary(val)
    if artifact_summary is not None:
        artifact_ids = ", ".join(artifact_summary["artifact_ids"])
        more = (
            f"... 共 {artifact_summary['artifact_count']} 个"
            if artifact_summary["artifact_count"] > len(artifact_summary["artifact_ids"])
            else ""
        )
        # 同时展示外层结构 key，方便下游 LLM 知道字段名（不展开值）
        struct_hint = _struct_outline(val)
        return (
            f"<dict-with-artifacts ids=[{artifact_ids}{more}] {struct_hint}>"
        )
    # 5) 其余结构化值：dump 后超 budget 自动降级为摘要
    try:
        dumped = json.dumps(val, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return f"<unserializable {type(val).__name__}>"
    if len(dumped.encode("utf-8")) > budget:
        if isinstance(val, list):
            return (
                f"<large-list len={len(val)} approx_bytes={len(dumped)} "
                f"(已截断，请通过 artifact 或节点输出原文查看)>"
            )
        if isinstance(val, dict):
            keys = list(val.keys())[:5]
            more = f", ...共 {len(val)} 个 key" if len(val) > 5 else ""
            return (
                f"<large-dict keys=[{', '.join(map(str, keys))}{more}] "
                f"approx_bytes={len(dumped)} (已截断)>"
            )
        return dumped[:budget] + "\n... (已截断)"
    return f"```json\n{dumped}\n```"


def _struct_outline(val: Any, max_keys: int = 5) -> str:
    """生成 dict / list 的轻量结构概述，不展开值，仅给 key/type 提示。"""
    if isinstance(val, dict):
        keys = list(val.keys())[:max_keys]
        more = f", ...共 {len(val)}" if len(val) > max_keys else ""
        return f"keys=[{', '.join(map(str, keys))}{more}]"
    if isinstance(val, list):
        return f"len={len(val)}"
    return f"type={type(val).__name__}"


def _format_structured_context(context: dict[str, Any]) -> str:
    """将 context 拆分为「用户需求」「前序节点输出」「其他上下文」三段可读文本。

    这样节点 agent 更容易理解自己需要处理什么，而非从一个
    巨大的 JSON blob 里自己找线索。
    """
    import logging as _logging
    _ctx_logger = _logging.getLogger(__name__)
    _ctx_logger.info(
        "[_format_structured_context] context keys=%s, sizes=%s",
        list(context.keys()),
        {k: len(json.dumps(v, ensure_ascii=False, default=str)) if isinstance(v, (dict, list, str)) else type(v).__name__
         for k, v in context.items()},
    )
    parts: list[str] = []

    user_request = context.get("_user_request")
    task_desc = context.get("_task_description")
    if user_request:
        parts.append(f"## 用户原始需求\n{user_request}")
    if task_desc:
        parts.append(f"## 任务描述（由调度者提供）\n{task_desc}")

    meta_keys = {"_input", "_user_request", "_task_description", "_model_override"}
    prev_outputs: dict[str, Any] = {}
    other_ctx: dict[str, Any] = {}
    for k, v in context.items():
        if k in meta_keys:
            continue
        if isinstance(v, dict) and v:
            prev_outputs[k] = v
        else:
            other_ctx[k] = v

    if prev_outputs:
        lines = ["## 前序节点输出"]
        for code, output in prev_outputs.items():
            formatted = _format_node_output(output)
            lines.append(f"### 节点「{code}」\n{formatted}")
        parts.append("\n\n".join(lines))

    if other_ctx:
        # 其他上下文（_input 等）也要走安全摘要，否则 _input.polygon 等大字段
        # 会原样 dump 到 prompt 中（理论上 polygon 不大，但同样的渲染路径未来
        # 会被复用，统一走摘要更稳）。
        parts.append(
            "## 其他上下文\n"
            + _format_node_output(snapshot_json(other_ctx), max_length=4000)
        )

    return "\n\n".join(parts)


def build_session_turn_message(
    *,
    node: TaskNodeDefinition,
    context: dict[str, Any],
    runtime_state: dict[str, Any],
    sleep_checkpoint: dict[str, Any],
    compensation_config: dict[str, Any],
    has_history: bool,
    event: dict[str, Any] | None = None,
) -> Msg:
    """构造当前回合发给 Agent 的 user message。"""
    if event is not None:
        wakeup_type = str(event.get("wakeup_type") or "").strip().lower()
        if wakeup_type == "external":
            title = "Resume the workflow node session after an external wakeup."
        elif wakeup_type == "timer":
            title = "Resume the workflow node session after the scheduled timer wakeup."
        elif wakeup_type == "timeout":
            title = "Resume the workflow node session after a callback timeout."
        else:
            title = "Resume the existing workflow node session."
    elif has_history:
        title = "Continue the existing workflow node session."
    else:
        title = "Start a new workflow node session."

    guidance_sections = build_session_event_guidance(node=node, event=event)

    structured_ctx = _format_structured_context(context)

    payload: dict[str, Any] = {
        "node": {"code": node.code, "name": node.name},
        "runtime_state": snapshot_json(runtime_state),
        "sleep_checkpoint": snapshot_json(sleep_checkpoint),
        "compensation_config": snapshot_json(compensation_config),
    }

    instruction = (
            "Below is the workflow state. Read the user request and "
            "previous node outputs carefully, call tools when needed, "
            "and **always** finish this turn by calling `generate_response` "
            "(action ∈ complete / wait_callback / wait_timer / fail). "
            "If you only want to ask the user something, wrap that question "
            "in `generate_response(action=\"wait_callback\", "
            "result={\"prompt\": \"<your question>\"}, ...)` — never end "
            "with bare assistant text."
        )

    return Msg(
        "user",
        (
            f"{title}\n\n"
            f"{instruction}\n\n"
            f"{guidance_sections}"
            f"{structured_ctx}\n\n"
            f"## 运行时状态\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        ),
        name="user",
    )


def build_session_event_guidance(
    *,
    node: TaskNodeDefinition,
    event: dict[str, Any] | None,
) -> str:
    """根据唤醒类型生成恢复执行时的附加提示。"""
    if event is None:
        return ""

    config = node.session_prompt_config
    wakeup_type = str(event.get("wakeup_type") or "").strip().lower()
    sections: list[str] = []

    if wakeup_type == "external":
        instruction = (
            config.exception_instruction.strip()
            if config and config.exception_instruction.strip()
            else "This session resumed from an external wakeup. Treat it as an abnormal signal, verify whether the expected workflow window was missed, and follow the exception handling path when appropriate."
        )
        sections.append(f"Exception Wakeup Instruction:\n{instruction}")
    else:
        instruction = (
            config.resume_instruction.strip()
            if config and config.resume_instruction.strip()
            else "This session resumed from a persisted workflow event. Re-check the latest workflow state and continue from the current business phase."
        )
        sections.append(f"Resume Instruction:\n{instruction}")

    return "\n\n".join(sections) + "\n\n"


def build_resume_event_message(event: dict[str, Any]) -> Msg:
    """把恢复事件包装成一条特殊消息，插入到 Agent 的上下文中。"""
    safe_event = snapshot_json(event)
    return Msg(
        "user",
        (
            "<resume_event>\n"
            f"{json.dumps(safe_event, ensure_ascii=False, default=str)}\n"
            "</resume_event>"
        ),
        name="workflow_runtime",
        metadata={
            "session_entry_type": "resume_event",
            "event": safe_event,
            "tool_name": str(event.get("wakeup_source") or "workflow_runtime"),
        },
    )
