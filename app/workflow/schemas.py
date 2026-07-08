"""Workflow 域 Pydantic Schema — 合并 templates / runs 两类 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    CompensationStatus,
    NodeExecutorType,
    NodeMode,
    NodeRunStatus,
    TaskRunStatus,
    TemplateStatus,
    WakeType,
)
from app.schemas.common import (
    AsyncNodeConfig,
    CapabilityBinding,
    CompensationRule,
    TimestampsMixin,
)


# ---------------------------------------------------------------------------
# Template schemas
# ---------------------------------------------------------------------------


class CanvasPosition(BaseModel):
    """模版编辑器画布上的节点坐标（仅 UI，不参与执行）。"""

    x: float = 0.0
    y: float = 0.0


class CanvasViewport(BaseModel):
    """模版编辑器画布的视口位置与缩放（仅 UI，不参与执行）。"""

    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0


class RunInputFieldDefinition(BaseModel):
    key: str
    label: str
    field_type: Literal["text", "textarea", "number", "datetime", "json"] = "text"
    description: str | None = None
    required: bool = False
    placeholder: str | None = None
    default_value: Any = None


class SessionPromptConfig(BaseModel):
    role: str = ""
    objective: str = ""
    rules: list[str] = Field(default_factory=list)
    success_criteria: str = ""
    resume_instruction: str = ""
    exception_instruction: str = ""
    output_instruction: str = ""


class TaskNodeDefinition(BaseModel):
    """工作流模板中单个节点的完整定义，包含执行方式、绑定的能力和提示词等。"""

    model_config = ConfigDict(from_attributes=True)

    seq: int = Field(ge=1)
    code: str
    name: str
    description: str | None = None
    mode: NodeMode = Field(
        default=NodeMode.SYNC,
        description="历史遗留 UI 标签；不影响运行时执行路径。",
    )
    executor: NodeExecutorType = Field(
        default=NodeExecutorType.AGENT,
        description=(
            "节点执行器：AGENT/DIRECT 走 LLM 驱动的 ReAct 节点；"
            "PYTHON 走 PythonNodeRuntime 调用 python_handler。"
        ),
    )
    prompt: str = ""
    python_handler: str | None = Field(
        default=None,
        description=(
            "PYTHON 执行器使用：Python callable 的 import 路径，"
            "形如 'app.workflow.handlers.my_handler:run'。"
            "callable 签名为 async (context, *, db_session, runtime_context, "
            "handler_config) -> dict。"
        ),
    )
    python_handler_config: dict[str, Any] = Field(
        default_factory=dict,
        description="PYTHON 执行器使用：透传给 handler 的可选配置，如批大小/超时/降级开关等。",
    )
    model: CapabilityBinding | None = None
    mcps: list[CapabilityBinding] = Field(default_factory=list)
    functions: list[CapabilityBinding] = Field(default_factory=list)
    knowledges: list[CapabilityBinding] = Field(default_factory=list)
    skill_codes: list[str] = Field(
        default_factory=list,
        description="挂载的 SKILL.md 编码列表；运行时其 markdown 正文会作为独立段落追加到节点 prompt。",
    )
    async_config: AsyncNodeConfig | None = Field(
        default=None,
        description="兼容等待策略配置；当前主编辑器不再写入。",
    )
    compensation: CompensationRule | None = Field(
        default=None,
        description="高级兼容字段：当前主编辑器无入口，但运行时仍兼容执行。",
    )
    canvas_position: CanvasPosition | None = None
    session_prompt_config: SessionPromptConfig | None = None
    human_interaction: "HumanInteractionConfig | None" = Field(
        default=None,
        description="高级兼容字段：当前主编辑器无入口，但运行时仍兼容执行。",
    )


class TaskTemplatePayload(BaseModel):
    code: str
    name: str
    description: str | None = None
    status: TemplateStatus = TemplateStatus.DRAFT
    run_input_schema: list[RunInputFieldDefinition] = Field(default_factory=list)
    nodes: list[TaskNodeDefinition] = Field(default_factory=list)
    canvas_viewport: CanvasViewport | None = None

    @model_validator(mode="after")
    def validate_nodes(self) -> "TaskTemplatePayload":
        sequences = [node.seq for node in self.nodes]
        if len(sequences) != len(set(sequences)):
            raise ValueError("node seq must be unique within a template version")

        codes = [node.code for node in self.nodes]
        if len(codes) != len(set(codes)):
            raise ValueError("node code must be unique within a template version")

        return self


class TaskTemplateCreate(TaskTemplatePayload):
    pass


class TaskTemplateUpdate(TaskTemplatePayload):
    pass


class TaskNodeRead(TimestampsMixin, TaskNodeDefinition):
    """节点定义的读取响应，附带所属版本 ID 和时间戳。"""

    template_version_id: str = Field(description="所属模板版本 ID")


class TaskTemplateVersionRead(TimestampsMixin):
    template_id: str
    version: int
    status: TemplateStatus
    definition_json: dict[str, Any]
    run_input_schema: list[RunInputFieldDefinition] = Field(default_factory=list)
    nodes: list[TaskNodeRead] = Field(default_factory=list)


class TaskTemplateRead(TimestampsMixin):
    code: str
    name: str
    description: str | None = None
    status: TemplateStatus
    latest_version: int
    run_input_schema: list[RunInputFieldDefinition] = Field(default_factory=list)
    canvas_viewport: CanvasViewport | None = None
    versions: list[TaskTemplateVersionRead] = Field(default_factory=list)


class TaskTemplateDeleteResponse(BaseModel):
    """模板删除的响应。"""

    deleted: bool = Field(description="是否删除成功")
    template_id: str = Field(description="被删除的模板 ID")


# ---------------------------------------------------------------------------
# Run schemas
# ---------------------------------------------------------------------------


class TaskRunCreate(BaseModel):
    """创建工作流运行的请求体，指定模板（或具体版本）和初始输入。"""

    template_id: str | None = Field(
        default=None,
        description="模板 ID，系统自动选取最新版本执行；与 template_version_id 二选一",
    )
    template_version_id: str | None = Field(
        default=None,
        description="模板版本 ID，精确指定要执行的版本；与 template_id 二选一",
    )
    input_json: dict[str, Any] = Field(
        default_factory=dict,
        description="运行的初始输入数据，作为第一个节点的 context 传入",
    )

    @model_validator(mode="after")
    def validate_selector(self) -> "TaskRunCreate":
        if not self.template_id and not self.template_version_id:
            raise ValueError("template_id or template_version_id is required")
        return self


class NodeRunRead(TimestampsMixin):
    task_run_id: str
    node_id: str
    seq: int
    code: str
    status: NodeRunStatus
    waiting_kind: str | None = None
    wake_type: WakeType | None = None
    compensation_status: CompensationStatus
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    callback_payload_json: dict[str, Any]
    session_messages_json: list[dict[str, Any]] = Field(default_factory=list)
    runtime_state_json: dict[str, Any] = Field(default_factory=dict)
    sleep_checkpoint_json: dict[str, Any] = Field(default_factory=dict)
    compensation_config_json: dict[str, Any] = Field(default_factory=dict)
    last_turn_summary: str | None = None
    last_tool_summary: str | None = None
    artifact_count: int = 0
    session_message_count: int = 0
    external_instance_id: str | None = None
    timeout_at: datetime | None = None
    error_message: str | None = None


class NodeRunArtifactSummaryRead(TimestampsMixin):
    id: str
    seq: int
    artifact_type: str
    source_tool_name: str | None = None
    preview_text: str = ""
    size_bytes: int = 0


class NodeRunArtifactRead(NodeRunArtifactSummaryRead):
    node_run_id: str
    content: Any = None
    content_sha256: str


class NodeSessionArtifacts(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    items: list[NodeRunArtifactSummaryRead] = Field(default_factory=list)


class NodeSessionRead(BaseModel):
    session_id: str
    flow_instance_id: str
    workflow_id: str | None = None
    task_run_id: str
    node_run_id: str
    node_id: str
    node_code: str
    node_name: str
    status: str
    waiting_kind: str | None = None
    wake_type: WakeType | None = None
    external_instance_id: str | None = None
    timeout_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    input: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    runtime_state: dict[str, Any] = Field(default_factory=dict)
    sleep_checkpoint: dict[str, Any] = Field(default_factory=dict)
    compensation_config: dict[str, Any] = Field(default_factory=dict)
    last_turn_summary: str | None = None
    last_tool_summary: str | None = None
    session_message_count: int = 0
    artifacts: NodeSessionArtifacts = Field(default_factory=NodeSessionArtifacts)
    error_message: str | None = None


class TaskRunRead(TimestampsMixin):
    """工作流运行的完整读取响应，包含所有节点执行记录。"""

    template_id: str = Field(description="所用模板 ID")
    template_version_id: str = Field(description="所用模板版本 ID")
    workflow_id: str | None = Field(
        default=None,
        description="Temporal Workflow ID，仅 Temporal 模式下有值；本地模式为 None",
    )
    status: TaskRunStatus = Field(
        description="运行状态：PENDING/RUNNING/WAITING/COMPLETED/FAILED"
    )
    current_seq: int | None = Field(
        default=None, description="当前正在执行（或等待）的节点序号，已完成时为 None"
    )
    input_json: dict[str, Any] = Field(description="运行的初始输入数据")
    context_json: dict[str, Any] = Field(
        description="运行时上下文，随节点执行滚动更新，聚合所有已完成节点的输出"
    )
    output_json: dict[str, Any] = Field(
        description="运行最终输出，全部节点完成后等于最终 context 快照"
    )
    error_message: str | None = Field(default=None, description="运行失败时的错误信息")
    node_runs: list[NodeRunRead] = Field(
        default_factory=list, description="所有节点执行记录，按 seq 排序"
    )


class TaskRunListItem(TimestampsMixin):
    """工作流运行列表的精简响应（不含完整节点记录，减少传输量）。"""

    template_id: str = Field(description="所用模板 ID")
    template_version_id: str = Field(description="所用模板版本 ID")
    template_name: str | None = Field(
        default=None, description="模板名称，由 JOIN 查询带出，便于列表展示"
    )
    workflow_id: str | None = Field(default=None, description="Temporal Workflow ID")
    status: TaskRunStatus = Field(description="运行状态")
    current_seq: int | None = Field(default=None, description="当前节点序号")
    current_node_code: str | None = Field(default=None, description="当前或最近活跃节点编码")
    current_node_summary: str | None = Field(
        default=None, description="当前节点最近一轮摘要"
    )
    last_tool_summary: str | None = Field(
        default=None, description="当前实例最近一次外部能力调用摘要"
    )
    error_message: str | None = Field(default=None, description="失败时的错误信息")
    node_count: int = Field(default=0, description="节点总数，便于前端展示进度")
    artifact_count: int = Field(default=0, description="累计剥离出的 artifact 数量")


class NodeCallbackRequest(BaseModel):
    """外部系统回调请求体，用于通知异步节点已完成。"""

    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="外部系统返回的业务数据，将写入 NodeRun.output_json",
    )
    status: str = Field(default="succeeded", description="回调状态标识，预留扩展用")


class NodeCallbackResponse(BaseModel):
    """回调接口的响应。"""

    accepted: bool = Field(description="回调是否被接受处理")
    task_run_id: str = Field(description="关联的工作流运行 ID")
    node_run_id: str = Field(description="关联的节点执行记录 ID")
    workflow_id: str | None = Field(
        default=None, description="Temporal Workflow ID（如有）"
    )
    message: str = Field(description="处理结果描述信息")


class TimeoutSweepItem(BaseModel):
    """单条超时扫描处理结果。"""

    task_run_id: str = Field(description="关联的工作流运行 ID")
    node_run_id: str = Field(description="被超时处理的节点执行记录 ID")
    node_code: str = Field(description="节点标识码")
    status: NodeRunStatus = Field(
        description="处理后的节点状态（通常为 TIMEOUT 或 FAILED）"
    )
    compensation_status: CompensationStatus = Field(description="补偿动作的执行结果")
    instance_id: str | None = Field(default=None, description="外部系统实例 ID")


class TimeoutSweepResponse(BaseModel):
    """超时扫描的批量响应。"""

    processed_count: int = Field(description="本次扫描处理的超时节点数量")
    items: list[TimeoutSweepItem] = Field(
        default_factory=list, description="每条超时节点的处理详情"
    )


# ---------------------------------------------------------------------------
# Human Interaction config (deferred to avoid circular import)
# ---------------------------------------------------------------------------

from app.chatbot.schemas import HumanInteractionConfig  # noqa: E402

TaskNodeDefinition.model_rebuild()
