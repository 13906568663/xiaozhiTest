"""能力绑定解析服务。

节点定义中的能力绑定（model/mcps/functions）以 code 引用全局注册表条目，
本服务在运行时将 code 解析为完整的 config，采用"注册表配置 + 节点覆盖"合并策略：
  merged_config = {**registry_config, **node_binding_config}
即节点绑定中的配置项优先级高于注册表中的默认配置。

functions：ref 优先匹配能力注册表 type=function 的 code；若无匹配且 ref 为
``external_agent`` 表主键，则按该外部智能体的 endpoint 合成 HTTP 工具配置。

BindingSource.NODE 的绑定跳过解析，其 config 已是完整配置，不需要查库。
"""

from __future__ import annotations

from typing import Any
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CapabilityRegistry
from app.domain.enums import BindingSource, CapabilityType, CompensationActionType
from app.schemas.common import CapabilityBinding, CompensationAction, CompensationRule
from app.skill.services import skills as skill_service
from app.workflow.schemas import TaskNodeDefinition


class CapabilityResolverService:
    async def resolve_node_definition(
        self,
        session: AsyncSession,
        node: TaskNodeDefinition,
        *,
        progressive_skills: bool = False,
    ) -> TaskNodeDefinition:
        """将节点定义中所有 GLOBAL 来源的能力绑定解析为完整配置，返回新的节点定义副本。

        ``progressive_skills``：是否走 "按需加载" 模式。
          - ``False``（默认 / workflow 节点）：节点上挂载的 SKILL.md 正文全部
            一次性注入 prompt，老语义保留以避免影响现有 workflow 行为；
          - ``True``（chatbot ReAct 入口）：仅注入 ``<available_skills>`` 索引
            （只含 ``code + description``），由 chat_engine 配对的
            ``load_skill`` 工具在 LLM 显式调用时再按需拉取正文，节省 token。
        """
        resolved_model = (
            await self.resolve_binding(session, node.model, CapabilityType.MODEL)
            if node.model
            else None
        )
        resolved_mcps = [
            await self._resolve_mcp_binding(session, binding)
            for binding in node.mcps
        ]
        resolved_functions = [
            await self._resolve_function_or_external_agent(session, binding)
            for binding in node.functions
        ]
        resolved_compensation = await self.resolve_compensation_rule(
            session, node.compensation
        )

        resolved_prompt = await self._inject_skill_prompts(
            session,
            node.prompt,
            node.skill_codes,
            progressive=progressive_skills,
        )

        return node.model_copy(
            update={
                "model": resolved_model,
                "mcps": resolved_mcps,
                "functions": resolved_functions,
                "compensation": resolved_compensation,
                "prompt": resolved_prompt,
            },
        )

    async def _inject_skill_prompts(
        self,
        session: AsyncSession,
        base_prompt: str,
        skill_codes: list[str],
        *,
        progressive: bool = False,
    ) -> str:
        """将节点挂载的 SKILL.md 装载到 prompt 末尾。

        ``progressive=False`` (默认 / workflow 节点)：把每个技能的完整正文以
        ``<skill name="..." description="...">...body...</skill>`` 形式包裹后
        全部追加到 prompt 末尾。语义直接、token 充裕场景下最稳。

        ``progressive=True``（chatbot ReAct）：仅注入索引段，每条只有
        ``code + description``，并提示模型必要时调用 ``load_skill(code)`` 工具
        拉取正文。配合 :func:`register_skill_loader` 注册的工具使用，未触发的
        技能正文不进上下文，避免 token 浪费。

        停用或缺失的技能静默跳过；节点原始 prompt 保持在最前。
        """
        if not skill_codes:
            return base_prompt
        entries = await skill_service.get_skills_with_meta(session, skill_codes)
        if not entries:
            return base_prompt

        if progressive:
            header = (
                "本节点装载了以下技能（Agent Skills）索引。每个技能是一份 "
                "SKILL.md 文档；这里只暴露 code + description，正文未加载。"
                "当某个技能的 description 匹配当前任务时，调用工具 "
                "load_skill(code) 拉取其正文并严格按其中指令执行；多个技能同时"
                "适用时，选择 description 最贴合当前任务的那一个；不需要的技能"
                "不要加载，避免无谓 token 消耗。同一技能在本会话内重复 load 会"
                "直接命中缓存，可放心多次调用。"
            )
            skill_blocks = [
                '<skill code="{code}" description="{desc}" />'.format(
                    code=entry["code"],
                    desc=(entry["description"] or "").replace('"', "&quot;"),
                )
                for entry in entries
            ]
        else:
            header = (
                "本节点为你装载了以下技能（Agent Skills）。每个技能是一份 SKILL.md 文档，"
                "包含其触发场景（description）与具体指令（正文）。当当前任务匹配某个技能的 "
                "description 时，严格遵循该技能正文中的指令完成任务；多个技能同时适用时，"
                "选择 description 最贴合当前任务的那一个。技能之间相互独立，未被触发的技能"
                "可忽略。"
            )
            skill_blocks = []
            for entry in entries:
                desc = (entry["description"] or "").replace('"', "&quot;")
                block = (
                    f'<skill name="{entry["code"]}" description="{desc}">\n'
                    f'{entry["body"].rstrip()}\n'
                    f"</skill>"
                )
                skill_blocks.append(block)

        block = (
            f'\n\n<available_skills description="{header}">\n\n'
            + "\n\n".join(skill_blocks)
            + "\n\n</available_skills>"
        )
        return (base_prompt or "") + block

    async def _resolve_mcp_binding(
        self,
        session: AsyncSession,
        binding: CapabilityBinding,
    ) -> CapabilityBinding:
        """解析 MCP 绑定：按 MCP 类型从能力注册表读取配置。"""
        if binding.ref is None or binding.source != BindingSource.GLOBAL:
            return binding

        resolved = await self.resolve_binding(session, binding, CapabilityType.MCP)
        if resolved is not None and resolved.config:
            return resolved

        return binding

    async def _resolve_function_or_external_agent(
        self,
        session: AsyncSession,
        binding: CapabilityBinding,
    ) -> CapabilityBinding:
        """按能力注册表 FUNCTION 解析绑定。"""
        if binding.ref is None or binding.source != BindingSource.GLOBAL:
            return binding

        resolved = await self.resolve_binding(session, binding, CapabilityType.FUNCTION)
        if resolved is not None and resolved.config and str(
            resolved.config.get("url") or ""
        ).strip():
            return resolved

        return binding

    async def resolve_binding(
        self,
        session: AsyncSession,
        binding: CapabilityBinding | None,
        capability_type: CapabilityType,
    ) -> CapabilityBinding | None:
        """解析单个能力绑定：从注册表读取基础配置，与绑定覆盖配置合并。

        能力 code 不存在时静默跳过（返回原始 binding），避免因能力删除导致运行失败。
        """
        if binding is None or binding.ref is None:
            return binding
        # NODE 来源的绑定已包含完整配置，无需查询注册表
        if binding.source != BindingSource.GLOBAL:
            return binding

        capability = await self._get_capability(session, capability_type, binding.ref)
        if capability is None:
            return binding

        # 节点绑定配置项优先：可覆盖注册表中的默认值
        merged_config = {
            **(capability.config_json or {}),
            **binding.config,
        }
        if capability_type == CapabilityType.FUNCTION:
            # 将注册表中的 code 和描述注入 tool_name/tool_description，
            # 供 ToolRegistry 自动生成工具描述
            merged_config.setdefault("tool_name", capability.code)
            if capability.description:
                merged_config.setdefault("tool_description", capability.description)

        return binding.model_copy(update={"ref": binding.ref, "config": merged_config})

    async def resolve_compensation_rule(
        self,
        session: AsyncSession,
        rule: CompensationRule | None,
    ) -> CompensationRule | None:
        """解析补偿规则中的能力绑定，与正常节点绑定采用相同的合并策略。"""
        if rule is None or rule.action is None:
            return rule

        action = rule.action
        if action.type == CompensationActionType.MCP:
            capability_ref = action.ref
            explicit_tool_name: str | None = None
            capability = await self._get_capability(
                session, CapabilityType.MCP, capability_ref
            )
            if capability is None and "." in capability_ref:
                candidate_ref, candidate_tool_name = capability_ref.rsplit(".", 1)
                capability = await self._get_capability(
                    session, CapabilityType.MCP, candidate_ref
                )
                if capability is not None:
                    capability_ref = candidate_ref
                    explicit_tool_name = candidate_tool_name.strip() or None
            if capability is not None:
                merged_config = {**(capability.config_json or {}), **action.config}
                if explicit_tool_name and not merged_config.get("tool_name"):
                    merged_config["tool_name"] = explicit_tool_name
                return rule.model_copy(
                    update={
                        "action": action.model_copy(
                            update={"ref": capability_ref, "config": merged_config}
                        )
                    },
                )

        if action.type == CompensationActionType.FUNCTION:
            capability = await self._get_capability(
                session, CapabilityType.FUNCTION, action.ref
            )
            if capability is not None:
                merged_config = {**(capability.config_json or {}), **action.config}
                merged_config.setdefault("tool_name", capability.code)
                if capability.description:
                    merged_config.setdefault("tool_description", capability.description)
                return rule.model_copy(
                    update={
                        "action": CompensationAction(
                            type=action.type,
                            ref=action.ref,
                            config=merged_config,
                            args_mapping=action.args_mapping,
                        ),
                    },
                )
        return rule

    async def _get_capability(
        self,
        session: AsyncSession,
        capability_type: CapabilityType,
        code: str,
    ) -> CapabilityRegistry | None:
        stmt = (
            sa.select(CapabilityRegistry)
            .where(CapabilityRegistry.type == capability_type)
            .where(CapabilityRegistry.code == code)
        )
        return (await session.scalars(stmt)).one_or_none()
