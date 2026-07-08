"""目标判定模块 — 当机器人配置了 goal_prompt 时，每轮对话后判断是否达成目标。

使用 LLM 分析完整对话历史和 goal_prompt，输出结构化判定结果。
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.capabilities.schemas import ModelProviderConfig
from app.core.config import get_settings
from app.db.models.chatbot import Chatbot, ChatMessage
from app.domain.enums import ModelApiMode
from app.runtime_core.provider import OpenAICompatProvider
from app.workflow.runtime.helpers import coerce_reasoning_effort


class GoalJudge:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def judge(
        self,
        bot: Chatbot,
        messages: list[ChatMessage],
        *,
        model_config: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """判断目标是否达成。

        Args:
            bot: 机器人配置。
            messages: 完整对话历史。
            model_config: 已解析的模型提供方配置（由调用方通过 CapabilityResolver 解析后传入）。

        Returns:
            (achieved, result) — achieved=True 时 result 为收集到的结构化数据。
        """
        provider = self._build_provider(model_config)
        if provider is None:
            return False, None

        conversation_text = "\n".join(
            f"[{msg.role}]: {msg.content}" for msg in messages if msg.content
        )

        system_text = (
            "你是一个目标判定助手。根据以下目标描述和对话历史，判断目标是否已经达成。\n\n"
            f"目标描述：{bot.goal_prompt}\n\n"
            "请以 JSON 格式回复，格式如下：\n"
            '{"achieved": true/false, "result": {...收集到的关键信息...}, "reason": "判断理由"}\n\n'
            "注意：\n"
            "- achieved 为 true 表示用户已经提供了目标要求的全部信息\n"
            "- result 中应包含从对话中提取的关键数据\n"
            "- 只返回 JSON，不要包含 markdown 代码块标记或其他文字"
        )
        user_text = f"对话历史：\n\n{conversation_text}"

        try:
            chat_messages = [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ]
            raw = (await provider.simple_chat(chat_messages, max_tokens=512)).strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            achieved = bool(parsed.get("achieved", False))
            result = parsed.get("result") if achieved else None
            return achieved, result
        except Exception:
            return False, None
        finally:
            try:
                await provider.aclose()
            except Exception:
                pass

    # Kept for backwards-compatibility with callers that import this symbol.
    def _build_model(self, model_binding: dict[str, Any] | None):  # noqa: D401
        return self._build_provider(model_binding)

    def _build_provider(
        self, model_binding: dict[str, Any] | None
    ) -> OpenAICompatProvider | None:
        model_config = ModelProviderConfig.model_validate(model_binding or {})
        api_mode = model_config.api_mode
        if api_mode not in (
            ModelApiMode.OPENAI_COMPATIBLE,
            ModelApiMode.DEEPSEEK_COMPATIBLE,
        ):
            return None

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
            model_config.api_host or self.settings.openai_base_url or ""
        ).strip() or None

        return OpenAICompatProvider(
            model=str(model_config.model_name or self.settings.default_model_name),
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
            reasoning_effort=coerce_reasoning_effort(model_config.reasoning_effort),
            max_tokens=512,
            stream=False,
            auth_header_name=model_config.auth_header_name,
            auth_header_scheme=model_config.auth_header_scheme,
        )
