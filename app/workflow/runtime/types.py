"""节点运行时的执行结果类型定义。

核心类型：
  - SessionTurnAction / NodeSessionDecision / SessionTurnResult：
    session-first 架构下所有节点统一使用的会话回合结果。
  - CompensationExecutionResult：补偿动作执行结果。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class CompensationExecutionResult(BaseModel):
    """补偿动作执行结果。"""

    ok: bool = True
    details: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class SessionTurnAction(str, Enum):
    """节点级 Agent Session 在一次推理回合后的控制动作。"""

    COMPLETE = "complete"
    WAIT_CALLBACK = "wait_callback"
    WAIT_TIMER = "wait_timer"
    FAIL = "fail"


class NodeSessionDecision(BaseModel):
    """ReAct 节点在一个回合结束时交给引擎的结构化控制结果。"""

    action: SessionTurnAction
    result: dict[str, Any] = Field(default_factory=dict)
    state_patch: dict[str, Any] = Field(default_factory=dict)
    sleep_checkpoint: dict[str, Any] = Field(default_factory=dict)
    compensation_config: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    instance_id: str | None = None
    timeout_seconds: int | None = None
    wake_at: datetime | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "NodeSessionDecision":
        if self.action == SessionTurnAction.WAIT_CALLBACK:
            if not self.instance_id:
                raise ValueError("instance_id is required for wait_callback action")
            if self.timeout_seconds is None or self.timeout_seconds < 1:
                raise ValueError(
                    "timeout_seconds must be >= 1 for wait_callback action"
                )

        if self.action == SessionTurnAction.WAIT_TIMER and self.wake_at is None:
            raise ValueError("wake_at is required for wait_timer action")

        if self.action == SessionTurnAction.FAIL and not self.error_message:
            raise ValueError("error_message is required for fail action")

        return self


class SessionTurnResult(BaseModel):
    """运行时对一次节点会话回合的执行结果封装。"""

    action: SessionTurnAction
    output: dict[str, Any] = Field(default_factory=dict)
    session_memory: dict[str, Any] = Field(default_factory=dict)
    session_messages: list[dict[str, Any]] = Field(default_factory=list)
    runtime_state: dict[str, Any] = Field(default_factory=dict)
    sleep_checkpoint: dict[str, Any] = Field(default_factory=dict)
    compensation_config: dict[str, Any] = Field(default_factory=dict)
    waiting_kind: str | None = None
    instance_id: str | None = None
    timeout_seconds: int | None = None
    wake_at: datetime | None = None
    error_message: str | None = None
    summary: str | None = None
