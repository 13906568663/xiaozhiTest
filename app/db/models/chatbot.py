"""Chatbot 域 ORM 模型。

核心概念：
  - Chatbot：机器人配置，包括系统提示词、能力绑定（模型/MCP/函数/知识库）等。
    配置了 goal_prompt 时（如工作流人机交互自动创建的临时机器人）会在每轮后做目标判定。
  - ChatSession：一次聊天会话；人机交互场景下携带 access_token 用于公开访问，
    目标达成后会话 completed，并通过 node_run 回调将结果回传工作流。
  - ChatMessage：会话中的单条消息，按 seq 排序。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_type
from app.domain.enums import ChatbotStatus, ChatbotType, ChatSessionStatus


class Chatbot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """机器人配置，定义了机器人的提示词和可用能力。"""

    __tablename__ = "chatbot"

    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    type: Mapped[ChatbotType] = mapped_column(
        sa.Enum(ChatbotType, native_enum=False),
        default=ChatbotType.NORMAL,
        nullable=False,
    )
    system_prompt: Mapped[str] = mapped_column(sa.Text(), default="", nullable=False)
    goal_prompt: Mapped[str] = mapped_column(sa.Text(), default="", nullable=False)
    model_binding: Mapped[dict] = mapped_column(json_type, default=dict)
    mcp_bindings: Mapped[list] = mapped_column(json_type, default=list)
    function_bindings: Mapped[list] = mapped_column(json_type, default=list)
    knowledge_bindings: Mapped[list] = mapped_column(json_type, default=list)
    skill_bindings: Mapped[list] = mapped_column(
        json_type,
        default=list,
        server_default=sa.text("'[]'"),
    )
    max_turns: Mapped[int] = mapped_column(sa.Integer(), default=50, nullable=False)
    icon: Mapped[str] = mapped_column(
        sa.String(32),
        default="🤖",
        server_default="🤖",
        nullable=False,
    )
    status: Mapped[ChatbotStatus] = mapped_column(
        sa.Enum(
            ChatbotStatus,
            native_enum=False,
            values_callable=lambda obj: [e.value for e in obj],
            validate_strings=True,
        ),
        default=ChatbotStatus.ACTIVE,
        server_default=ChatbotStatus.ACTIVE.value,
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(
        sa.ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )

    sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="chatbot",
        cascade="all, delete-orphan",
    )


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次聊天会话；公开链接场景下通过 access_token 访问。"""

    __tablename__ = "chat_session"

    chatbot_id: Mapped[str] = mapped_column(
        sa.ForeignKey("chatbot.id", ondelete="CASCADE"),
        index=True,
    )
    access_token: Mapped[str | None] = mapped_column(
        sa.String(255), unique=True, nullable=True, index=True
    )
    status: Mapped[ChatSessionStatus] = mapped_column(
        sa.Enum(ChatSessionStatus, native_enum=False),
        default=ChatSessionStatus.ACTIVE,
        nullable=False,
    )
    node_run_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("node_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_run_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("task_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    context_json: Mapped[dict] = mapped_column(json_type, default=dict)
    result_json: Mapped[dict] = mapped_column(json_type, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    chatbot: Mapped[Chatbot] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """聊天消息，按 seq 排序记录会话中的每条消息。"""

    __tablename__ = "chat_message"

    session_id: Mapped[str] = mapped_column(
        sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), default="", nullable=False)
    tool_calls_json: Mapped[list] = mapped_column(json_type, default=list)
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    # 用户对 assistant 回复的反馈评分：1=赞(👍)，-1=踩(👎)，None=未评价。
    # 仅对 role="assistant" 的消息有意义；外嵌智能体在消息操作栏提供入口。
    feedback_rating: Mapped[int | None] = mapped_column(
        sa.SmallInteger(), nullable=True
    )
    # 踩/赞时可附带的文字意见，便于运营回收用户对生成结果的具体反馈。
    feedback_comment: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ToolCallLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """工具调用日志，专门用于外部 API 调用的统计与审计。

    每一次 Agent 触发的工具调用（无论 HTTP function / MCP / 会话控制）都会
    在 POST_ACTING hook 阶段同步落一条日志到本表，独立 session 写入，失败
    不阻塞业务主流程。

    设计要点：
      - **轻量列存**：把统计常用的维度（tool_name / category / status_code /
        duration_ms / is_success）拍平成列，避免对 chat_message.tool_calls_json
        做 JSONB 展开查询。
      - **session_id 绑定**：JOIN chat_session 才能拿到会话归属信息；不在
        本表冗余用户字段，避免 ChatSession.context_json 后续变更时双写不一致。
      - **arguments_json 已 mask 敏感字段**：参见 tool_call_logger 中的
        ``_SENSITIVE_KEY_PATTERNS``。
    """

    __tablename__ = "tool_call_log"

    session_id: Mapped[str] = mapped_column(
        sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    tool_category: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, index=True
    )
    http_method: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    http_status_code: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    duration_ms: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=0, server_default="0"
    )
    is_success: Mapped[bool] = mapped_column(
        sa.Boolean(),
        nullable=False,
        default=True,
        server_default=sa.text("true"),
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    arguments_json: Mapped[dict] = mapped_column(json_type, default=dict)
    response_preview: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
