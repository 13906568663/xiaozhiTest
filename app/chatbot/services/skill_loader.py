"""按需加载 SKILL.md 正文的工具实现。

配合 :mod:`app.workflow.services.capability_resolver` 中 ``progressive=True``
模式使用：system_prompt 仅注入技能索引（``code + description``），LLM 判断
当前任务匹配某技能时显式调用本工具拉取完整正文。

设计要点：
  * **越权防护**：传入 ``code`` 必须在本次注册时声明的 ``skill_codes`` 白名单内，
    否则 ``is_error=True`` 返回，避免模型偷取未挂载的技能。
  * **会话内缓存**：闭包内维护 ``cache: dict[str, str]``，第二次加载同一 code
    直接命中，``cached=True`` 提示模型同一技能不必反复 load。
  * **细分错误**：分别区分"未挂载 / 不存在 / 已停用 / 解析失败"四种 NG 状态，
    错误信息明确，方便模型自主纠错。
  * **零绑定零工具**：``skill_codes`` 为空时不注册 ``load_skill``，避免给
    LLM 提供没有使用场景的死工具。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime_core.tool_protocol import (
    ToolCategory,
    ToolRegistry,
    ToolResult,
)
from app.skill.services import skills as skill_service
from app.skill.services.skills import SkillSourceError, parse_skill_source

logger = logging.getLogger(__name__)


_LOAD_SKILL_DESCRIPTION = (
    "按需加载已挂载技能（SKILL.md）的完整正文。仅当 <available_skills> 索引中"
    "某条技能的 description 与当前任务相匹配时调用本工具拉取其正文，并严格按正文"
    "中的指令执行后续操作。同一会话内重复加载会命中缓存（cached=true），不要因为"
    "缓存命中就额外重复调用——拿到正文后专注于按其指令推进任务即可。"
)

_LOAD_SKILL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": (
                "要加载的技能 code，必须是 <available_skills> 索引里列出的 code 之一。"
            ),
        },
    },
    "required": ["code"],
    "additionalProperties": False,
}


def register_skill_loader(
    registry: ToolRegistry,
    *,
    db_session: AsyncSession,
    skill_codes: list[str],
) -> None:
    """给当前 ReAct 会话注册 ``load_skill`` 工具。

    Args:
        registry: 当前节点构建好的工具注册表。
        db_session: 当前请求使用的异步数据库会话，工具体内复用同一连接。
        skill_codes: 本机器人在 ``chatbot.skill_bindings`` 中挂载的 SKILL.md
            code 列表；为空时直接 return（不注册工具），避免给 LLM 提供没有
            使用场景的死工具。
    """
    allowed = sorted({c.strip() for c in skill_codes if isinstance(c, str) and c.strip()})
    if not allowed:
        return

    allowed_set = set(allowed)
    body_cache: dict[str, str] = {}

    async def load_skill(code: str = "", **_: Any) -> ToolResult:
        if not isinstance(code, str) or not code.strip():
            return ToolResult(
                output={
                    "ok": False,
                    "error": "参数 code 必填，且需为非空字符串。",
                    "available": allowed,
                },
                is_error=True,
            )
        normalized = code.strip()

        if normalized not in allowed_set:
            return ToolResult(
                output={
                    "ok": False,
                    "error": (
                        f"技能 '{normalized}' 未挂载到当前机器人。"
                        "只能加载 <available_skills> 索引中列出的技能。"
                    ),
                    "available": allowed,
                },
                is_error=True,
            )

        if normalized in body_cache:
            return ToolResult(
                output={
                    "ok": True,
                    "code": normalized,
                    "body": body_cache[normalized],
                    "cached": True,
                },
            )

        try:
            skill = await skill_service.get_skill_by_code(db_session, normalized)
        except Exception as exc:  # noqa: BLE001 - 数据库异常以错误结果回传 LLM
            logger.exception("load_skill: 查询 skill=%s 时数据库异常", normalized)
            return ToolResult(
                output={
                    "ok": False,
                    "error": f"加载技能 '{normalized}' 时发生服务端错误：{exc}",
                },
                is_error=True,
            )

        if skill is None:
            return ToolResult(
                output={
                    "ok": False,
                    "error": (
                        f"技能 '{normalized}' 在数据库中未找到，"
                        "可能已被删除。请检查机器人的技能绑定配置。"
                    ),
                },
                is_error=True,
            )

        if skill.status != "active":
            return ToolResult(
                output={
                    "ok": False,
                    "error": (
                        f"技能 '{normalized}' 当前状态为 '{skill.status}'，未启用。"
                    ),
                },
                is_error=True,
            )

        try:
            _, body = parse_skill_source(skill.source)
        except SkillSourceError as exc:
            return ToolResult(
                output={
                    "ok": False,
                    "error": f"技能 '{normalized}' 内容解析失败：{exc}",
                },
                is_error=True,
            )

        body_cache[normalized] = body
        return ToolResult(
            output={
                "ok": True,
                "code": normalized,
                "body": body,
                "cached": False,
            },
        )

    load_skill.__name__ = "load_skill"

    registry.register_function(
        name="load_skill",
        description=_LOAD_SKILL_DESCRIPTION,
        parameters=_LOAD_SKILL_PARAMETERS,
        fn=load_skill,
        category=ToolCategory.KNOWLEDGE,
        is_read_only=True,
    )


__all__ = ["register_skill_loader"]
