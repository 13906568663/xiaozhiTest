"""Chatbot 域 Pydantic Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.enums import ChatbotStatus, ChatbotType, ChatSessionStatus
from app.schemas.common import CapabilityBinding, TimestampsMixin


# ---------------------------------------------------------------------------
# Chatbot schemas
# ---------------------------------------------------------------------------


class ChatbotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    system_prompt: str = ""
    icon: str = Field(default="🤖", max_length=32)
    status: ChatbotStatus = Field(default=ChatbotStatus.ACTIVE)
    model_binding: dict[str, Any] = Field(default_factory=dict)
    mcp_bindings: list[dict[str, Any]] = Field(default_factory=list)
    function_bindings: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_bindings: list[dict[str, Any]] = Field(default_factory=list)
    skill_bindings: list[str] = Field(
        default_factory=list,
        description=(
            "挂载的 SKILL.md code 列表；运行时其 markdown 正文会以 "
            "<available_skills> 块追加到 system_prompt 末尾，模型按场景触发。"
        ),
    )
    max_turns: int = Field(default=50, ge=1, le=1000)


class ChatbotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    system_prompt: str | None = None
    icon: str | None = Field(default=None, max_length=32)
    status: ChatbotStatus | None = None
    model_binding: dict[str, Any] | None = None
    mcp_bindings: list[dict[str, Any]] | None = None
    function_bindings: list[dict[str, Any]] | None = None
    knowledge_bindings: list[dict[str, Any]] | None = None
    skill_bindings: list[str] | None = None
    max_turns: int | None = Field(default=None, ge=1, le=1000)


class ChatbotRead(TimestampsMixin):
    name: str
    description: str | None = None
    type: ChatbotType
    system_prompt: str = ""
    goal_prompt: str = ""
    icon: str = "🤖"
    status: ChatbotStatus = ChatbotStatus.ACTIVE
    model_binding: dict[str, Any] = Field(default_factory=dict)
    mcp_bindings: list[dict[str, Any]] = Field(default_factory=list)
    function_bindings: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_bindings: list[dict[str, Any]] = Field(default_factory=list)
    skill_bindings: list[str] = Field(
        default_factory=list,
        description="挂载的 SKILL.md code 列表（与节点 skill_codes 同一套机制）。",
    )
    max_turns: int = 50
    created_by: str | None = None
    session_count: int = Field(default=0, description="会话总数")


class ChatbotDeleteResponse(BaseModel):
    deleted: bool
    chatbot_id: str


# ---------------------------------------------------------------------------
# ChatSession schemas
# ---------------------------------------------------------------------------


class ChatSessionCreate(BaseModel):
    chatbot_id: str


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatSessionBranchRequest(BaseModel):
    before_seq: int | None = Field(
        default=None,
        ge=1,
        description="只复制 seq 小于该值的消息；为空时复制整个会话。",
    )


class ChatSessionSummaryRead(TimestampsMixin):
    chatbot_id: str
    status: ChatSessionStatus
    title: str = Field(default="新对话")
    last_message_preview: str | None = None
    message_count: int = Field(default=0)


class ChatSessionRead(TimestampsMixin):
    chatbot_id: str
    access_token: str | None = None
    status: ChatSessionStatus
    node_run_id: str | None = None
    task_run_id: str | None = None
    context_json: dict[str, Any] = Field(default_factory=dict)
    result_json: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    message_count: int = Field(default=0)


class ChatSessionDeleteResponse(BaseModel):
    deleted: bool
    session_id: str


# ---------------------------------------------------------------------------
# ChatMessage schemas
# ---------------------------------------------------------------------------


class ChatMessageSend(BaseModel):
    content: str = Field(min_length=1)


class ChatFileUploadResult(BaseModel):
    """文件上传解析结果。"""

    file_name: str
    file_size: int
    content_type: Literal["document", "image"]
    parsed_text: str | None = None
    data_url: str | None = None
    file_data_url: str | None = None


class ChatMessageFeedback(BaseModel):
    """对单条 assistant 回复的反馈：评分 + 可选文字意见。"""

    rating: Literal[1, -1, 0] = Field(
        description="评分：1=赞(👍)，-1=踩(👎)，0=取消已有评价。",
    )
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="可选的文字意见，用于补充对生成结果的具体反馈。",
    )


class ChatMessageRead(TimestampsMixin):
    session_id: str
    role: str
    content: str
    tool_calls_json: list[dict[str, Any]] = Field(default_factory=list)
    seq: int
    feedback_rating: int | None = Field(
        default=None,
        description="用户反馈评分：1=赞，-1=踩，None=未评价。",
    )
    feedback_comment: str | None = Field(
        default=None,
        description="用户反馈的文字意见。",
    )


class ChatResponse(BaseModel):
    """聊天回复，包含 assistant 消息和会话状态。"""

    message: ChatMessageRead
    session_status: ChatSessionStatus
    goal_achieved: bool = False
    goal_result: dict[str, Any] | None = None
    usage: dict[str, Any] | None = Field(
        default=None,
        description="本轮 LLM token 用量（input/output/cache_read/requests）。",
    )


# ---------------------------------------------------------------------------
# Public chat schemas
# ---------------------------------------------------------------------------


class PublicChatInfo(BaseModel):
    """公开聊天页面所需的机器人信息。"""

    bot_name: str
    bot_description: str | None = None
    session_status: ChatSessionStatus
    messages: list[ChatMessageRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# HumanInteraction config (for workflow integration)
# ---------------------------------------------------------------------------


class HumanInteractionConfig(BaseModel):
    """人机交互配置，节点进入等待时自动创建临时聊天机器人。"""

    enabled: bool = False
    bot_name: str = ""
    bot_system_prompt: str = ""
    goal_prompt: str = ""
    model_binding: CapabilityBinding | None = None
    mcp_bindings: list[CapabilityBinding] = Field(default_factory=list)
    function_bindings: list[CapabilityBinding] = Field(default_factory=list)
    knowledge_bindings: list[CapabilityBinding] = Field(default_factory=list)
    skill_bindings: list[str] = Field(
        default_factory=list,
        description="挂载的 SKILL.md code 列表；交互机器人 system_prompt 自动追加。",
    )
    max_turns: int = Field(default=50, ge=1)
    timeout_minutes: int = Field(default=1440, ge=1)
