"""节点运行时，使用 ``app.runtime_core.ConversationRuntime`` 执行工作流节点 session。

核心入口：
  - run_session_turn：执行一个可恢复的 ReAct 会话回合
  - execute_compensation：补偿动作执行，在节点失败/超时后触发回滚操作

具体能力分布在同包的子模块中：
  - helpers              通用工具函数
  - template             占位符 / 模板解析
  - prompt               Prompt 构建
  - session_serializer   会话轨迹序列化
  - http_invoker         HTTP function 调用
  - mcp_invoker          MCP 客户端管理
  - tool_registry        工具注册
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from app.capabilities.schemas import ModelProviderConfig
from app.core.config import get_settings
from app.domain.enums import CompensationActionType, ModelApiMode
from app.runtime_core.compression import CompressionConfig
from app.runtime_core.formatter import ChatFormatter
from app.runtime_core.hooks import HookRunner
from app.runtime_core.memory import Memory
from app.runtime_core.messages import Msg
from app.runtime_core.provider import OpenAICompatProvider
from app.runtime_core.runtime import (
    ConversationRuntime,
    DEFAULT_FINISH_TOOL_NAME,
    FinishConfig,
    StreamEvent,
)
from app.runtime_core.tool_protocol import ToolContext, ToolRegistry
from app.workflow.runtime.agent_hooks import register_audit_hooks
from app.workflow.runtime.helpers import (
    coerce_agent_execution_timeout_seconds,
    coerce_memory_compression_threshold,
    coerce_reasoning_effort,
    snapshot_json,
)
from app.workflow.runtime.http_invoker import invoke_http_function_binding
from app.workflow.runtime.mcp_invoker import (
    close_mcp_clients,
    invoke_mcp_binding,
)
from app.workflow.runtime.prompt import (
    build_resume_event_message,
    build_session_system_prompt,
    build_session_turn_message,
    resolve_node_prompts,
)
from app.workflow.runtime.session_serializer import serialize_session_messages
from app.workflow.runtime.template import resolve_value_template
from app.workflow.runtime.tool_registry import (
    register_functions,
    register_knowledge_tools,
    register_mcps,
    register_python_handler_tools,
    register_runtime_info_tools,
    register_session_control_tools,
)
from app.workflow.runtime.types import (
    CompensationExecutionResult,
    NodeSessionDecision,
    SessionTurnAction,
    SessionTurnResult,
)
from app.workflow.schemas import TaskNodeDefinition

logger = logging.getLogger(__name__)

# 单节点 turn 持久化到 runtime_state["_actions"] 的最大动作条数。
# 长 turn 下 max_iters 可达数百，单条 output 又被截到 4KB，无上限的话
# 最坏数百 × 4KB ≈ 2MB 单行 JSON 列会把 DB / 前端打爆。
MAX_PERSISTED_ACTIONS = 400


def _cap_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """超出 MAX_PERSISTED_ACTIONS 时保留头 50 + 尾余量，中间用 marker 占位。

    保留头部是为了观察「这一轮起手做了什么」，保留尾部是为了观察「最后死在哪」，
    丢中段；marker 里带 ``dropped`` 计数，便于排查时一眼看出"中间漏了 N 条"。
    """
    total = len(actions)
    if total <= MAX_PERSISTED_ACTIONS:
        return actions
    head_keep = 50
    tail_keep = MAX_PERSISTED_ACTIONS - head_keep - 1
    dropped = total - head_keep - tail_keep
    return [
        *actions[:head_keep],
        {
            "type": "_truncated",
            "dropped": dropped,
            "total": total,
            "head_kept": head_keep,
            "tail_kept": tail_keep,
        },
        *actions[total - tail_keep:],
    ]


def node_expects_structured_result(node: TaskNodeDefinition) -> bool:
    """节点是否要求 LLM 通过 ``generate_response`` 交付结构化 ``result``。

    配置了 ``output_instruction`` 且语义上要求结构化 result 的节点（如多步骤
    结构化流程节点），若 LLM 只输出 plain text 而不调 finish tool，不应 auto-wrap
    成 COMPLETE（会污染下游 context），而应判 FAIL 让上层可见并重试。
    """
    config = node.session_prompt_config
    if config is None:
        return False
    instruction = (config.output_instruction or "").strip()
    if not instruction:
        return False
    structured_markers = (
        "result 严格",
        "generate_response",
        "下游",
    )
    return any(marker in instruction for marker in structured_markers)


def _node_session_decision_schema() -> dict[str, Any]:
    """Build the JSON schema for the finish tool's parameters from the
    ``NodeSessionDecision`` pydantic model.
    """
    schema = NodeSessionDecision.model_json_schema()
    # Strip pydantic-only $defs / title cruft to a flat OpenAI-friendly shape.
    schema.pop("title", None)
    return schema


def _validate_node_session_decision(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the finish payload via pydantic; raises on error."""
    NodeSessionDecision.model_validate(payload)
    return dict(payload)


class NodeRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # 补偿执行
    # ------------------------------------------------------------------

    async def execute_compensation(
        self,
        node: TaskNodeDefinition,
        payload: dict[str, Any],
    ) -> CompensationExecutionResult:
        """执行节点补偿动作（FUNCTION / MCP 两条通路）。"""
        rule = node.compensation
        if not rule or not rule.action:
            return CompensationExecutionResult(ok=True, details={"skipped": True})

        action = rule.action
        if action.type == CompensationActionType.FUNCTION:
            resolved_kwargs = resolve_value_template(
                action.args_mapping, payload=payload, node=node,
            )
            if not resolved_kwargs:
                resolved_kwargs = snapshot_json(payload)
            try:
                result, _ = await invoke_http_function_binding(
                    action.config,
                    call_kwargs=resolved_kwargs,
                    payload=payload,
                    node=node,
                )
            except Exception as exc:
                return CompensationExecutionResult(ok=False, error_message=str(exc))
            return CompensationExecutionResult(ok=True, details=result)

        mcp_result = await invoke_mcp_binding(
            action.config,
            binding_ref=action.ref,
            call_kwargs=resolve_value_template(
                dict(action.config.get("call_args") or {}) | dict(action.args_mapping),
                payload=payload,
                node=node,
            ),
            fallback_payload=payload,
            name_hint=f"{node.code}-compensation",
        )
        if not mcp_result["ok"]:
            return CompensationExecutionResult(
                ok=False, error_message=mcp_result["error_message"],
            )
        return CompensationExecutionResult(ok=True, details=mcp_result["result"])

    # ------------------------------------------------------------------
    # 会话回合执行
    # ------------------------------------------------------------------

    async def run_session_turn(
        self,
        node: TaskNodeDefinition,
        context: dict[str, Any],
        *,
        session_memory: dict[str, Any] | None = None,
        runtime_state: dict[str, Any] | None = None,
        sleep_checkpoint: dict[str, Any] | None = None,
        compensation_config: dict[str, Any] | None = None,
        event: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
        db_session: Any | None = None,
        event_publisher: Any | None = None,
    ) -> SessionTurnResult:
        """执行一个可恢复节点会话回合。"""
        node = resolve_node_prompts(node, context)
        registry = ToolRegistry()
        register_session_control_tools(registry, node)
        register_runtime_info_tools(
            registry, node, runtime_context=runtime_context or {},
        )
        register_functions(registry, node, context)
        # AGENT 节点若配了 python_handler，把它包成一个粗粒度工具供 LLM 调用
        # （大模型决策 + Python 干重活）；纯 PYTHON 节点不会走到这里。
        register_python_handler_tools(
            registry,
            node,
            context,
            db_session=db_session,
            runtime_context=runtime_context or {},
        )
        connected_mcp_clients, mcp_tool_display_names = await register_mcps(
            registry, node, db_session=db_session
        )
        if db_session and node.knowledges:
            register_knowledge_tools(registry, node, db_session=db_session)

        # 子专家不再注册 PlanNotebook：每个 NodeRuntime 只执行一个
        # TaskNode，本身就是"主 AI plan 中的一步"。如果再让子 LLM 自己
        # 拆 subtask，只会让它消耗 token 写一份和主 plan 重复（且更弱）
        # 的进度报告，且没有任何下游消费。要观测子专家进度请直接看
        # runtime_state["_actions"]（tool_call / tool_result 时间线）。

        memory = Memory()
        if session_memory:
            memory.load_state_dict(session_memory, strict=False)

        # Provider 复用：上层（LocalRunExecutor / run_plan 等）可在
        # runtime_context 里注入 ``_provider_pool``——一个 dict，key 为 provider
        # 配置 hash，value 为已建好的 OpenAICompatProvider。命中即跳过新建
        # httpx.AsyncClient + TLS 握手（国内网关单次 0.5–2s）。pool 生命周期
        # 由注入者负责（用完自己 aclose_all），node 内只是"借用"。
        provider_pool: dict[str, OpenAICompatProvider] | None = None
        if isinstance(runtime_context, dict):
            candidate_pool = runtime_context.get("_provider_pool")
            if isinstance(candidate_pool, dict):
                provider_pool = candidate_pool
        owns_provider = True
        provider: OpenAICompatProvider | None = None
        if provider_pool is not None:
            cache_key = self._provider_cache_key(node)
            cached = provider_pool.get(cache_key)
            if isinstance(cached, OpenAICompatProvider):
                provider = cached
                owns_provider = False
            else:
                provider = self._build_provider(node)
                if provider is not None:
                    provider_pool[cache_key] = provider
                    owns_provider = False
        else:
            provider = self._build_provider(node)
        if provider is None:
            try:
                return self._build_mock_result(
                    node,
                    context,
                    event,
                    memory,
                    runtime_state,
                    sleep_checkpoint,
                    compensation_config,
                    mcp_tool_display_names,
                )
            finally:
                await close_mcp_clients(connected_mcp_clients)

        knowledge_context = None
        if db_session and node.knowledges:
            knowledge_context = await self._build_knowledge_context(
                node, context, db_session,
            )

        try:
            sys_prompt = build_session_system_prompt(
                node,
                knowledge_context=knowledge_context,
            )
            turn_message = build_session_turn_message(
                node=node,
                context=context,
                runtime_state=runtime_state or {},
                sleep_checkpoint=sleep_checkpoint or {},
                compensation_config=compensation_config or {},
                has_history=bool(session_memory),
                event=event,
            )
            input_messages: list[Msg] = []
            if event:
                input_messages.append(build_resume_event_message(event))
            input_messages.append(turn_message)

            timeout_seconds = self._agent_execution_timeout_seconds(node)
            compression_threshold = self._memory_compression_threshold(node)

            hook_runner = HookRunner()
            register_audit_hooks(hook_runner)

            actions_collected: list[dict[str, Any]] = []
            on_stream = self._build_node_stream_sink(
                publisher=event_publisher,
                actions=actions_collected,
                node=node,
            )

            # 即时 artifact 后处理：让大工具返回当场转 artifact + stub 替换。
            # 这样 LLM 在同一 turn 后续 iter 中能看到 artifact_id，便于在最终
            # generate_response 的 result 里用 {"__artifact": "<id>"} 引用，
            # 绕开 max_tokens 输出截断风险。仅当本 turn 有 db_session + node_run_id
            # 时才挂钩；其余场景维持原行为。
            tool_output_postprocessor = None
            _artifact_node_run_id = (runtime_context or {}).get("node_run_id")
            if db_session is not None and _artifact_node_run_id:
                from app.workflow.services.session_assets import (
                    store_tool_output_as_artifact,
                )

                # turn 级缓存：同一份内容（sha + tool）重复出现时，跳过 DB SELECT
                # 直接复用 artifact_id。LLM 偶尔会陷入"调同一工具同一参数"的循环，
                # 没缓存的话每次都要 SELECT 一遍 NodeRunArtifact。
                _artifact_sha_cache: dict[str, str] = {}

                async def _postprocess(tool_name: str, output_text: str) -> str:
                    return await store_tool_output_as_artifact(
                        db_session,
                        node_run_id=str(_artifact_node_run_id),
                        tool_name=tool_name,
                        output_text=output_text,
                        sha_cache=_artifact_sha_cache,
                    )

                tool_output_postprocessor = _postprocess

            runtime = ConversationRuntime(
                provider=provider,
                registry=registry,
                memory=memory,
                formatter=self._build_formatter(node),
                hooks=hook_runner,
                compression=CompressionConfig(
                    enable=True,
                    trigger_threshold_tokens=compression_threshold,
                    keep_recent=3,
                ),
                sys_prompt=sys_prompt,
                finish=FinishConfig(
                    name=DEFAULT_FINISH_TOOL_NAME,
                    description=(
                        "Call this special tool exactly once, as the final "
                        "action of this turn, to deliver your structured "
                        "control decision (action / result / state_patch / "
                        "sleep_checkpoint / compensation_config / ...) back "
                        "to the workflow engine."
                    ),
                    parameters=_node_session_decision_schema(),
                    validator=_validate_node_session_decision,
                ),
                # max_iters 历史值 200 / 500 偏大：实际业务里子专家 99% 在
                # 20 轮以内自然收敛，剩余 1% 多是 LLM 死循环（restart→cancel→
                # redo）吃满配额。收紧到 80 / 150 后兜底超时仍由
                # agent_execution_timeout_seconds 控制；提早 break 让"循环卡死"
                # 类故障在 2 分钟内暴露，而不是 30 分钟。
                max_iters=80,
                name=f"session-node-{node.code}",
                on_stream=on_stream,
                tool_output_postprocessor=tool_output_postprocessor,
            )

            reply = await self._await_runtime_reply(
                runtime=runtime,
                input_messages=input_messages,
                node=node,
                timeout_seconds=timeout_seconds,
                runtime_context=runtime_context or {},
                compression_threshold=compression_threshold,
            )

            decision_payload = reply.metadata.get("decision") or {}
            memory_state = memory.state_dict()
            # 防御：decision_payload 为空，或带 _error / _raw 标记（来自
            # ConversationRuntime._capture_finish 的 validator 失败兜底）
            # 又或者 model_validate 直接失败时，统一走 FAIL 兜底而不是让
            # NodeRuntime 抛异常炸掉整个节点。否则上层 LocalRunExecutor
            # 看到的就是 "Node session crashed" 这种致命错误。
            decision: NodeSessionDecision | None = None
            if decision_payload and "_error" not in decision_payload:
                try:
                    decision = NodeSessionDecision.model_validate(decision_payload)
                except Exception:
                    logger.exception(
                        "Failed to validate NodeSessionDecision (node_code=%s); "
                        "falling back to FAIL result.",
                        getattr(node, "code", None),
                    )
                    decision = None

            if decision is None:
                result = self._build_empty_decision_result(
                    node,
                    reply,
                    memory_state,
                    runtime_state,
                    sleep_checkpoint,
                    compensation_config,
                    event,
                    mcp_tool_display_names,
                )
            else:
                result = self._build_decision_result(
                    node,
                    decision,
                    memory_state,
                    runtime_state,
                    sleep_checkpoint,
                    compensation_config,
                    event,
                    mcp_tool_display_names,
                )

            # 把节点过程的 tool_call/tool_result 时间线持久化到
            # runtime_state["_actions"]，前端可在节点详情中回放。
            # 超长 turn 做窗口化裁剪，避免单行 JSON 暴涨。
            if actions_collected:
                result.runtime_state["_actions"] = _cap_actions(actions_collected)
            return result
        finally:
            # provider 在 L278 的 None-check 后已被 narrowed 为非空（mock 分支
            # 已经提前 return），这里只需判断"是否本节点 own 该 provider"。
            if owns_provider:
                try:
                    await provider.aclose()
                except Exception:
                    pass
            await close_mcp_clients(connected_mcp_clients)

    # ------------------------------------------------------------------
    # 知识库上下文注入
    # ------------------------------------------------------------------

    @staticmethod
    async def _build_knowledge_context(
        node: TaskNodeDefinition,
        context: dict[str, Any],
        db_session: Any,
    ) -> str | None:
        """为 inject_mode=auto 的知识库绑定自动检索并构建上下文文本。"""
        from app.domain.enums import KnowledgeInjectMode
        from app.knowledge.services import knowledge_base as kb_svc
        from app.knowledge.services.retrieval import search_by_text

        auto_bindings = [
            b
            for b in node.knowledges
            if b.config.get("inject_mode") in (KnowledgeInjectMode.AUTO, "auto")
        ]
        if not auto_bindings:
            return None

        query_text = context.get("input", "") or context.get("query", "")
        if not query_text:
            query_text = " ".join(
                str(v) for v in context.values() if isinstance(v, str) and v.strip()
            )[:500]
        if not query_text:
            return None

        all_chunks: list[str] = []
        for binding in auto_bindings:
            kb_code = binding.ref
            if not kb_code:
                continue
            kb = await kb_svc.get_knowledge_base_by_code(db_session, kb_code)
            if kb is None:
                continue
            top_k = int(binding.config.get("top_k", 5))
            score_threshold = binding.config.get("score_threshold")
            resolved_embedding_config = await kb_svc.resolve_kb_embedding_config(
                db_session, kb,
            )
            results = await search_by_text(
                db_session,
                knowledge_base_id=kb.id,
                query=str(query_text),
                embedding_model=kb.embedding_model,
                embedding_config=resolved_embedding_config,
                top_k=top_k,
                score_threshold=float(score_threshold)
                if score_threshold is not None
                else None,
            )
            for r in results:
                all_chunks.append(
                    f"[来源: {r.document_title} | 相关度: {r.score:.2f}]\n{r.content}"
                )

        if not all_chunks:
            return None
        return "\n\n---\n\n".join(all_chunks)

    # ------------------------------------------------------------------
    # Stream sink：节点内部 thinking/tool_call/tool_result 的实时分发
    # ------------------------------------------------------------------

    @staticmethod
    def _build_node_stream_sink(
        *,
        publisher: Any | None,
        actions: list[dict[str, Any]],
        node: TaskNodeDefinition,
    ) -> Any:
        """构造 ConversationRuntime.on_stream 回调。

        作用：
        - tool_call / tool_result：追加到 ``actions`` 列表（用于持久化），
          同时通过 ``publisher`` 实时推送给前端。
        - thinking_delta：仅实时推送（数据量大不持久化）。
        - text_delta：仅实时推送给前端 plan 面板做"子专家正在输出"提示。
          不进 ``actions`` 持久化——最终结构化结果走 ``generate_response`` 的
          ``result`` 字段；text 持久化由 session_messages（NodeRun 整理后落库）
          负责，前端在节点完成后用 transcript fetch 拿到完整版。
        - done：忽略（runtime 已经发了节点级 done，前端按 status 切换）。
        """

        async def _sink(event: StreamEvent) -> None:
            try:
                if event.type == "tool_call":
                    data = dict(event.data or {})
                    actions.append({
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "arguments": data.get("arguments"),
                    })
                    if publisher is not None:
                        await publisher("node.tool_call", data)
                elif event.type == "tool_result":
                    data = dict(event.data or {})
                    actions.append({
                        "id": data.get("id"),
                        "name": data.get("tool_name"),
                        "is_error": data.get("is_error"),
                        "output": data.get("output"),
                        "type": "result",
                    })
                    if publisher is not None:
                        await publisher("node.tool_result", data)
                elif event.type == "thinking_delta":
                    if publisher is not None:
                        await publisher(
                            "node.thinking_delta", dict(event.data or {}),
                        )
                elif event.type == "text_delta":
                    # 子专家最终面向 generate_response.result 的纯文本流：转发
                    # 给前端，让 plan 面板/子专家抽屉能像 thinking 一样实时
                    # 看到子专家在写什么。和 thinking_delta 一样不做持久化
                    # （前端用 nodeRuntimeMap 累积，节点完成后由抽屉的
                    # transcript fetch 落到 session_messages 持久数据上）。
                    if publisher is not None:
                        await publisher(
                            "node.text_delta", dict(event.data or {}),
                        )
            except Exception:
                # 任何 sink 异常都不能影响主对话循环
                logger.exception(
                    "Node stream sink failed (node=%s, event=%s)",
                    node.code,
                    event.type,
                )

        return _sink

    # ------------------------------------------------------------------
    # 模型构建
    # ------------------------------------------------------------------

    def _build_provider(self, node: TaskNodeDefinition) -> OpenAICompatProvider | None:
        """从节点绑定构造 OpenAI-compatible provider 实例。

        当 API key 缺失时返回 None，由调用方走 mock 分支。
        """
        model_config = ModelProviderConfig.model_validate(
            node.model.config if node.model else {},
        )
        api_mode = model_config.api_mode
        if api_mode not in (
            ModelApiMode.OPENAI_COMPATIBLE,
            ModelApiMode.DEEPSEEK_COMPATIBLE,
        ):
            raise ValueError(f"Unsupported model api_mode '{api_mode}'.")

        if model_config.api_path != "/chat/completions":
            raise ValueError(
                "OpenAI-compatible model provider currently only supports /chat/completions.",
            )

        api_key = (
            model_config.api_key
            or (
                os.getenv(model_config.api_key_env)
                if model_config.api_key_env
                else None
            )
            or self.settings.openai_api_key
        )
        if not api_key:
            return None

        base_url = str(
            model_config.api_host or self.settings.openai_base_url or "https://api.openai.com/v1",
        ).strip()

        reasoning = coerce_reasoning_effort(model_config.reasoning_effort)
        extra_body: dict[str, Any] = {}
        if reasoning is None:
            extra_body["enable_thinking"] = False

        return OpenAICompatProvider(
            api_key=str(api_key),
            base_url=base_url,
            model=str(model_config.model_name or self.settings.default_model_name),
            # 默认 4096：1024 太小会让"按 output_instruction 输出结构化 result"
            # 直接 finish_reason=length 被切，触发 _run_turn_inner 里"空 reply +
            # 待 tool_result"路径的额外重试，反而拖慢整轮。模型/网关侧若不允许
            # 4096 由 provider._extract_max_tokens_upper_bound 自动回退到上限。
            max_tokens=int(model_config.max_tokens or 4096),
            stream=bool(model_config.stream),
            reasoning_effort=reasoning,
            extra_body=extra_body or None,
            auth_header_name=model_config.auth_header_name,
            auth_header_scheme=model_config.auth_header_scheme,
        )

    @staticmethod
    def _provider_cache_key(node: TaskNodeDefinition) -> str:
        """根据 model binding 生成一个稳定 hash key，供 provider_pool 命中复用。

        把所有可能影响"HTTP 连接 + provider 配置"的字段都纳入：base_url、
        model_name、api_key、auth_header、max_tokens、reasoning_effort、stream。
        其它字段（如 extra_body 中的 enable_thinking）与 reasoning_effort 联动
        已经隐含。
        """
        import hashlib
        import json as _json

        model_config = ModelProviderConfig.model_validate(
            node.model.config if node.model else {},
        )
        # 注：api_key 也纳入 key，避免不同 chatbot 共享同一 base_url 但
        # 鉴权头不同时拿到错的 provider 实例。
        payload = {
            "api_host": str(model_config.api_host or ""),
            "api_path": str(model_config.api_path or ""),
            "model": str(model_config.model_name or ""),
            "max_tokens": int(model_config.max_tokens or 4096),
            "stream": bool(model_config.stream),
            "reasoning_effort": coerce_reasoning_effort(
                model_config.reasoning_effort,
            ),
            "auth_header_name": str(model_config.auth_header_name or ""),
            "auth_header_scheme": str(model_config.auth_header_scheme or ""),
            "api_key": str(
                model_config.api_key or model_config.api_key_env or "",
            ),
        }
        raw = _json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_formatter(
        node: TaskNodeDefinition,
        *,
        promote_tool_result_images: bool = False,
    ) -> ChatFormatter:
        model_config = ModelProviderConfig.model_validate(
            node.model.config if node.model else {},
        )
        return ChatFormatter(
            deepseek_compat=(
                model_config.api_mode == ModelApiMode.DEEPSEEK_COMPATIBLE
            ),
            promote_tool_result_images=promote_tool_result_images,
        )

    @staticmethod
    def _memory_compression_threshold(node: TaskNodeDefinition) -> int:
        model_config = ModelProviderConfig.model_validate(
            node.model.config if node.model else {},
        )
        return coerce_memory_compression_threshold(
            model_config.memory_compression_threshold,
        )

    @staticmethod
    def _agent_execution_timeout_seconds(node: TaskNodeDefinition) -> int:
        raw_model_config = node.model.config if node.model else {}
        model_config = ModelProviderConfig.model_validate(raw_model_config)
        return coerce_agent_execution_timeout_seconds(
            model_config.agent_execution_timeout_seconds,
        )

    @staticmethod
    async def _await_runtime_reply(
        *,
        runtime: ConversationRuntime,
        input_messages: list[Msg],
        node: TaskNodeDefinition,
        timeout_seconds: float,
        runtime_context: dict[str, Any],
        compression_threshold: int,
    ) -> Msg:
        start = time.perf_counter()
        logger.info(
            "[%s] Runtime turn started (timeout=%ss, max_iters=%s, compression_threshold=%s, task_run_id=%s, node_run_id=%s).",
            node.code,
            timeout_seconds,
            runtime.max_iters,
            compression_threshold,
            runtime_context.get("task_run_id"),
            runtime_context.get("node_run_id"),
        )
        ctx = ToolContext(
            db_session=None,
            agent_id=node.code,
            runtime_context=runtime_context,
        )
        try:
            reply = await asyncio.wait_for(
                runtime.run_turn(input_messages, context=ctx),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            logger.error(
                "[%s] Runtime turn timed out after %.2fs (configured=%ss, task_run_id=%s, node_run_id=%s).",
                node.code,
                time.perf_counter() - start,
                timeout_seconds,
                runtime_context.get("task_run_id"),
                runtime_context.get("node_run_id"),
            )
            raise asyncio.TimeoutError(
                f"Node {node.code} runtime turn timed out after {timeout_seconds}s."
            ) from exc
        except Exception:
            logger.exception(
                "[%s] Runtime turn failed after %.2fs (task_run_id=%s, node_run_id=%s).",
                node.code,
                time.perf_counter() - start,
                runtime_context.get("task_run_id"),
                runtime_context.get("node_run_id"),
            )
            raise
        logger.info(
            "[%s] Runtime turn finished in %.2fs (task_run_id=%s, node_run_id=%s).",
            node.code,
            time.perf_counter() - start,
            runtime_context.get("task_run_id"),
            runtime_context.get("node_run_id"),
        )
        return reply

    # ------------------------------------------------------------------
    # 状态组装
    # ------------------------------------------------------------------

    @staticmethod
    def _build_runtime_state(
        *,
        previous_state: dict[str, Any],
        state_patch: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        next_state = {
            **snapshot_json(previous_state),
            **snapshot_json(state_patch),
        }
        if summary:
            next_state["_summary"] = summary
        return next_state

    @staticmethod
    def _build_sleep_checkpoint(
        *,
        previous_checkpoint: dict[str, Any],
        decision: NodeSessionDecision | None = None,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checkpoint = snapshot_json(previous_checkpoint)
        if decision is not None:
            checkpoint.update(snapshot_json(decision.sleep_checkpoint))
            if decision.action == SessionTurnAction.WAIT_CALLBACK:
                checkpoint.setdefault("status", "waiting")
                checkpoint["waiting_kind"] = "callback"
                checkpoint["instance_id"] = decision.instance_id
                checkpoint["timeout_seconds"] = decision.timeout_seconds
            elif decision.action == SessionTurnAction.WAIT_TIMER:
                checkpoint.setdefault("status", "sleeping")
                checkpoint["waiting_kind"] = "timer"
                checkpoint["scheduled_wakeup_time"] = (
                    decision.wake_at.isoformat() if decision.wake_at else None
                )
            elif decision.action in {
                SessionTurnAction.COMPLETE,
                SessionTurnAction.FAIL,
            }:
                checkpoint["status"] = decision.action.value

        if event:
            checkpoint["wakeup_result"] = snapshot_json(event)
        return checkpoint

    @staticmethod
    def _build_compensation_config(
        *,
        previous_config: dict[str, Any],
        latest_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **snapshot_json(previous_config),
            **snapshot_json(latest_config),
        }

    # ------------------------------------------------------------------
    # 结果构建辅助
    # ------------------------------------------------------------------

    def _build_mock_result(
        self,
        node: TaskNodeDefinition,
        context: dict[str, Any],
        event: dict[str, Any] | None,
        memory: Memory,
        runtime_state: dict[str, Any] | None,
        sleep_checkpoint: dict[str, Any] | None,
        compensation_config: dict[str, Any] | None,
        mcp_tool_display_names: dict[str, str],
    ) -> SessionTurnResult:
        mock_output = {
            "mock": True,
            "node_code": node.code,
            "message": (
                f"OPENAI_API_KEY not set; returned mock session output for {node.code}."
            ),
            "context": snapshot_json(context),
            "event": snapshot_json(event or {}),
        }
        memory_state = memory.state_dict()
        return SessionTurnResult(
            action=SessionTurnAction.COMPLETE,
            output=mock_output,
            session_memory=memory_state,
            session_messages=serialize_session_messages(
                node=node,
                memory_state=memory_state,
                final_result=mock_output,
                mcp_tool_display_names=mcp_tool_display_names,
            ),
            runtime_state=self._build_runtime_state(
                previous_state=runtime_state or {},
                state_patch=runtime_state or {},
                summary="mock session completion",
            ),
            sleep_checkpoint=self._build_sleep_checkpoint(
                previous_checkpoint=sleep_checkpoint or {},
                event=event,
            ),
            compensation_config=self._build_compensation_config(
                previous_config=compensation_config or {},
                latest_config=compensation_config or {},
            ),
            summary="mock session completion",
        )

    def _build_empty_decision_result(
        self,
        node: TaskNodeDefinition,
        reply: Msg,
        memory_state: dict[str, Any],
        runtime_state: dict[str, Any] | None,
        sleep_checkpoint: dict[str, Any] | None,
        compensation_config: dict[str, Any] | None,
        event: dict[str, Any] | None,
        mcp_tool_display_names: dict[str, str],
    ) -> SessionTurnResult:
        """LLM 漏调 generate_response 时的兜底。

        历史行为：直接判 FAIL，错误信息「did not emit a workflow control
        decision」。但实际生产里这种「漏调」99% 是子专家 LLM 写完一段总结
        / 询问问题就直接收尾，业务上是成功的——硬判 FAIL 会让前端 plan
        面板显示红色 ✗ 误报、上层 chatbot 也无法继续推进。

        新行为（治本兜底）：
          1. 抓 reply 里的纯文本内容；
          2. 没有任何文本 → 仍然按 FAIL（这种是真崩了）；
          3. 有非空文本 → 启发式包装：
               - 文本中带「请确认 / 请问 / 是否 / 请选择 / ?」等问句标志
                 → 包装成 ``COMPLETE``（不强行 WAIT_CALLBACK，因为缺
                 instance_id；让上层 plan_prompt 第 3 条引导主 AI
                 复述该文本并询问用户即可）；
               - 否则 → 包装成 ``COMPLETE``。
          4. ``output.text`` 保留原文；额外打 ``_auto_wrapped: True``
             与 ``_auto_wrap_reason`` 让排查者一看便知；
          5. WARNING 级别 log 记录节点 code，便于盯 prompt 改进。
        """
        text = (reply.get_text_content() or "").strip()
        if not text:
            return SessionTurnResult(
                action=SessionTurnAction.FAIL,
                output={
                    "text": "",
                    "raw": reply.to_dict(),
                },
                session_memory=memory_state,
                session_messages=serialize_session_messages(
                    node=node,
                    memory_state=memory_state,
                    mcp_tool_display_names=mcp_tool_display_names,
                ),
                runtime_state=self._build_runtime_state(
                    previous_state=runtime_state or {},
                    state_patch=runtime_state or {},
                ),
                sleep_checkpoint=self._build_sleep_checkpoint(
                    previous_checkpoint=sleep_checkpoint or {},
                    event=event,
                ),
                compensation_config=self._build_compensation_config(
                    previous_config=compensation_config or {},
                    latest_config=compensation_config or {},
                ),
                error_message=(
                    f"Node session {node.code} did not emit a workflow control "
                    f"decision and produced no text either; treated as FAIL."
                ),
            )

        if node_expects_structured_result(node):
            logger.warning(
                "[%s] LLM did not emit generate_response but node requires "
                "structured result; treating as FAIL (text_len=%d).",
                node.code,
                len(text),
            )
            return SessionTurnResult(
                action=SessionTurnAction.FAIL,
                output={
                    "text": text[:2000],
                    "raw": reply.to_dict(),
                    "_auto_wrap_rejected": True,
                },
                session_memory=memory_state,
                session_messages=serialize_session_messages(
                    node=node,
                    memory_state=memory_state,
                    mcp_tool_display_names=mcp_tool_display_names,
                ),
                runtime_state=self._build_runtime_state(
                    previous_state=runtime_state or {},
                    state_patch=runtime_state or {},
                ),
                sleep_checkpoint=self._build_sleep_checkpoint(
                    previous_checkpoint=sleep_checkpoint or {},
                    event=event,
                ),
                compensation_config=self._build_compensation_config(
                    previous_config=compensation_config or {},
                    latest_config=compensation_config or {},
                ),
                error_message=(
                    f"Node {node.code} requires generate_response(action=complete, "
                    f"result={{...}}) per output_instruction, but the LLM ended "
                    f"with plain text only (len={len(text)}). Downstream nodes "
                    f"would receive wrong context if auto-completed."
                ),
            )

        looks_like_question = any(
            marker in text
            for marker in (
                "请确认", "请问", "是否", "请选择", "您要", "您是否",
                "需要您", "等待您", "等待用户", "等您", "请回复",
                "?", "？",
            )
        )
        wrap_reason = (
            "asked-user"
            if looks_like_question
            else "plain-text-completion"
        )
        logger.warning(
            "[%s] LLM did not emit generate_response, auto-wrapping as COMPLETE "
            "(reason=%s, text_len=%d). Consider strengthening the node prompt.",
            node.code, wrap_reason, len(text),
        )

        return SessionTurnResult(
            action=SessionTurnAction.COMPLETE,
            output={
                "text": text,
                "raw": reply.to_dict(),
                "_auto_wrapped": True,
                "_auto_wrap_reason": wrap_reason,
            },
            session_memory=memory_state,
            session_messages=serialize_session_messages(
                node=node,
                memory_state=memory_state,
                final_result={
                    "text": text,
                    "_auto_wrapped": True,
                    "_auto_wrap_reason": wrap_reason,
                },
                mcp_tool_display_names=mcp_tool_display_names,
            ),
            runtime_state=self._build_runtime_state(
                previous_state=runtime_state or {},
                state_patch=runtime_state or {},
                summary=f"auto-wrapped ({wrap_reason})",
            ),
            sleep_checkpoint=self._build_sleep_checkpoint(
                previous_checkpoint=sleep_checkpoint or {},
                event=event,
            ),
            compensation_config=self._build_compensation_config(
                previous_config=compensation_config or {},
                latest_config=compensation_config or {},
            ),
            summary=f"auto-wrapped ({wrap_reason})",
        )

    def _build_decision_result(
        self,
        node: TaskNodeDefinition,
        decision: NodeSessionDecision,
        memory_state: dict[str, Any],
        runtime_state: dict[str, Any] | None,
        sleep_checkpoint: dict[str, Any] | None,
        compensation_config: dict[str, Any] | None,
        event: dict[str, Any] | None,
        mcp_tool_display_names: dict[str, str],
    ) -> SessionTurnResult:
        next_runtime_state = self._build_runtime_state(
            previous_state=runtime_state or {},
            state_patch=decision.state_patch,
            summary=decision.summary,
        )
        next_sleep_checkpoint = self._build_sleep_checkpoint(
            previous_checkpoint=sleep_checkpoint or {},
            decision=decision,
            event=event,
        )
        next_compensation_config = self._build_compensation_config(
            previous_config=compensation_config or {},
            latest_config=decision.compensation_config,
        )
        return SessionTurnResult(
            action=decision.action,
            output=snapshot_json(decision.result),
            session_memory=memory_state,
            session_messages=serialize_session_messages(
                node=node,
                memory_state=memory_state,
                final_result=(
                    decision.result
                    if decision.action
                    in {SessionTurnAction.COMPLETE, SessionTurnAction.FAIL}
                    else None
                ),
                mcp_tool_display_names=mcp_tool_display_names,
            ),
            runtime_state=next_runtime_state,
            sleep_checkpoint=next_sleep_checkpoint,
            compensation_config=next_compensation_config,
            waiting_kind=(
                "callback"
                if decision.action == SessionTurnAction.WAIT_CALLBACK
                else "timer"
                if decision.action == SessionTurnAction.WAIT_TIMER
                else None
            ),
            instance_id=decision.instance_id,
            timeout_seconds=decision.timeout_seconds,
            wake_at=decision.wake_at,
            error_message=decision.error_message,
            summary=decision.summary,
        )


__all__ = ["NodeRuntime"]
