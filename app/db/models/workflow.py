"""Workflow 域 ORM 模型。

核心概念：
  - TaskTemplate / TaskTemplateVersion：工作流模板及版本快照，一旦 ACTIVE 不可修改，
    修改需创建新版本，确保历史运行记录可溯源。
  - TaskNode：版本下的节点定义（每个节点即一个 session stage），
    config_json 存储 prompt、能力绑定、等待/补偿策略等。
  - TaskRun：一次工作流执行实例，持有执行过程中的输入/上下文/输出快照。
  - NodeRun：单个节点 session 的执行记录，status 驱动调度逻辑，
    session 相关字段（messages / runtime_state / sleep_checkpoint 等）
    支持休眠-恢复和多轮 ReAct 会话。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_type
from app.domain.enums import (
    CompensationStatus,
    NodeExecutorType,
    NodeMode,
    NodeRunStatus,
    TaskRunStatus,
    TemplateStatus,
    WakeType,
)


class TaskTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """工作流模板元数据，每个模板可有多个不可变版本。"""

    __tablename__ = "task_template"

    code: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[TemplateStatus] = mapped_column(
        sa.Enum(TemplateStatus, native_enum=False),
        default=TemplateStatus.DRAFT,
        nullable=False,
    )
    # 记录当前最新版本号，便于快速获取最新版，避免 MAX(version) 聚合查询
    latest_version: Mapped[int] = mapped_column(sa.Integer(), default=1)

    versions: Mapped[list["TaskTemplateVersion"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TaskTemplateVersion.version",
    )


class TaskTemplateVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """工作流模板版本快照，ACTIVE 后不允许修改节点定义。

    definition_json 存储创建时的完整 DSL 快照，供审计和回放使用。
    """

    __tablename__ = "task_template_version"
    __table_args__ = (
        sa.UniqueConstraint("template_id", "version", name="uq_template_version"),
    )

    template_id: Mapped[str] = mapped_column(
        sa.ForeignKey("task_template.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    status: Mapped[TemplateStatus] = mapped_column(
        sa.Enum(TemplateStatus, native_enum=False),
        default=TemplateStatus.ACTIVE,
        nullable=False,
    )
    definition_json: Mapped[dict] = mapped_column(json_type, default=dict)

    template: Mapped[TaskTemplate] = relationship(back_populates="versions")
    nodes: Mapped[list["TaskNode"]] = relationship(
        back_populates="template_version",
        cascade="all, delete-orphan",
        order_by="TaskNode.seq",
    )


class TaskNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """模板版本中的单个 session stage 定义。

    seq 决定执行顺序；code 在同一版本内唯一，用于日志和上下文引用。
    config_json 包含节点的完整配置（prompt、能力绑定、等待/补偿策略等），
    运行时统一通过 run_session_turn 解析执行。
    """

    __tablename__ = "task_node"
    __table_args__ = (
        sa.UniqueConstraint("template_version_id", "seq", name="uq_template_node_seq"),
        sa.UniqueConstraint(
            "template_version_id", "code", name="uq_template_node_code"
        ),
    )

    template_version_id: Mapped[str] = mapped_column(
        sa.ForeignKey("task_template_version.id", ondelete="CASCADE"),
        index=True,
    )
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    # 历史遗留标签，仅用于 UI 提示和 async_config 门控
    mode: Mapped[NodeMode] = mapped_column(
        sa.Enum(NodeMode, native_enum=False),
        nullable=False,
    )
    # 历史遗留字段，当前所有节点统一使用 AGENT
    executor: Mapped[NodeExecutorType] = mapped_column(
        sa.Enum(NodeExecutorType, native_enum=False),
        default=NodeExecutorType.AGENT,
        nullable=False,
    )
    config_json: Mapped[dict] = mapped_column(json_type, default=dict)

    template_version: Mapped[TaskTemplateVersion] = relationship(back_populates="nodes")


class TaskRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次工作流执行实例。

    template_id / template_version_id 使用 RESTRICT 级联删除，
    确保历史运行记录在模板被删除前必须先被清理，防止数据孤立。
    context_json 在执行过程中滚动更新，记录最新的节点输出聚合上下文。
    """

    __tablename__ = "task_run"

    template_id: Mapped[str] = mapped_column(
        sa.ForeignKey("task_template.id", ondelete="RESTRICT"),
        index=True,
    )
    template_version_id: Mapped[str] = mapped_column(
        sa.ForeignKey("task_template_version.id", ondelete="RESTRICT"),
        index=True,
    )
    # 历史遗留列，当前始终为 None，保留以兼容已有数据库 schema
    workflow_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, unique=True
    )
    status: Mapped[TaskRunStatus] = mapped_column(
        sa.Enum(TaskRunStatus, native_enum=False),
        default=TaskRunStatus.PENDING,
        nullable=False,
    )
    current_seq: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    input_json: Mapped[dict] = mapped_column(json_type, default=dict)
    context_json: Mapped[dict] = mapped_column(json_type, default=dict)
    output_json: Mapped[dict] = mapped_column(json_type, default=dict)
    error_message: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    node_runs: Mapped[list["NodeRun"]] = relationship(
        back_populates="task_run",
        cascade="all, delete-orphan",
        order_by="NodeRun.seq",
    )


class NodeRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """单个节点 session 的执行记录。

    external_instance_id：session 等待外部回调时的实例 ID，用于超时扫描和回调路由。
    timeout_at：session 等待的超时截止时间，超时扫描器定期检查此字段。
    wake_type：记录 session 被唤醒的方式（外部回调 or 超时），用于审计和补偿逻辑判断。
    session 相关字段（session_memory_json / session_messages_json / runtime_state_json /
    sleep_checkpoint_json / compensation_config_json）用于休眠-恢复和多轮 ReAct 会话。
    """

    __tablename__ = "node_run"
    __table_args__ = (
        sa.UniqueConstraint("task_run_id", "seq", name="uq_node_run_seq"),
    )

    task_run_id: Mapped[str] = mapped_column(
        sa.ForeignKey("task_run.id", ondelete="CASCADE"),
        index=True,
    )
    node_id: Mapped[str] = mapped_column(
        sa.ForeignKey("task_node.id", ondelete="RESTRICT"),
        index=True,
    )
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[NodeRunStatus] = mapped_column(
        sa.Enum(NodeRunStatus, native_enum=False),
        default=NodeRunStatus.PENDING,
        nullable=False,
    )
    waiting_kind: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    wake_type: Mapped[WakeType | None] = mapped_column(
        sa.Enum(WakeType, native_enum=False),
        nullable=True,
    )
    compensation_status: Mapped[CompensationStatus] = mapped_column(
        sa.Enum(CompensationStatus, native_enum=False),
        default=CompensationStatus.NONE,
        nullable=False,
    )
    input_json: Mapped[dict] = mapped_column(json_type, default=dict)
    output_json: Mapped[dict] = mapped_column(json_type, default=dict)
    # 外部系统通过回调接口传入的原始 payload，保存以供审计
    callback_payload_json: Mapped[dict] = mapped_column(json_type, default=dict)
    # 会话型节点的 runtime memory 快照，用于回调/定时触发后恢复到同一节点
    session_memory_json: Mapped[dict] = mapped_column(json_type, default=dict)
    # 会话型节点的消息轨迹，给回放/审计/人工接管使用
    session_messages_json: Mapped[list] = mapped_column(json_type, default=list)
    # 会话型节点的结构化业务状态，供下一回合恢复与引擎判断
    runtime_state_json: Mapped[dict] = mapped_column(json_type, default=dict)
    # 会话型节点最近一次进入等待时的休眠检查点
    sleep_checkpoint_json: Mapped[dict] = mapped_column(json_type, default=dict)
    # 会话型节点当前补偿策略和执行结果快照
    compensation_config_json: Mapped[dict] = mapped_column(json_type, default=dict)
    # 当前节点最近一轮对话的轻量摘要，供列表页和后续记忆抽取复用
    last_turn_summary: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # 最近一次外部能力调用摘要，优先保留业务工具而非内部控制工具
    last_tool_summary: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # 当前节点累计剥离出的 artifact 数量
    artifact_count: Mapped[int] = mapped_column(sa.Integer(), default=0, nullable=False)
    # 序列化后的 session 消息条数，便于前端和压缩策略做轻量展示
    session_message_count: Mapped[int] = mapped_column(
        sa.Integer(), default=0, nullable=False
    )
    external_instance_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        index=True,
    )
    timeout_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    task_run: Mapped[TaskRun] = relationship(back_populates="node_runs")
    artifacts: Mapped[list["NodeRunArtifact"]] = relationship(
        back_populates="node_run",
        cascade="all, delete-orphan",
        order_by="NodeRunArtifact.seq",
    )


class NodeRunArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """节点会话中被剥离的大体积消息内容。

    主要承载 observation / action / final 等高体积 payload，
    NodeRun.session_messages_json 中仅保留指向 artifact 的轻量 stub。
    """

    __tablename__ = "node_run_artifact"
    __table_args__ = (
        sa.UniqueConstraint(
            "node_run_id",
            "content_sha256",
            "artifact_type",
            "source_tool_name",
            name="uq_node_run_artifact_content",
        ),
    )

    node_run_id: Mapped[str] = mapped_column(
        sa.ForeignKey("node_run.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    artifact_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    # 用空串而非 NULL：唯一约束在 Postgres 下对 NULL 列视为"互不相等"，
    # 会让同 (node_run_id, sha, type, NULL) 的 artifact 反复重复入库；
    # 这里强制空串作为"无来源工具"的哨兵，让去重生效。
    source_tool_name: Mapped[str] = mapped_column(
        sa.String(255), nullable=False, default="", server_default="",
    )
    preview_text: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    content_json: Mapped[object | None] = mapped_column(json_type, nullable=True)
    size_bytes: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    content_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    node_run: Mapped[NodeRun] = relationship(back_populates="artifacts")
