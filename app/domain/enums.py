"""全域共享枚举定义。

所有枚举均继承 str，使其可直接序列化为 JSON 字符串，
并与数据库中 native_enum=False 模式的字符串列保持一致。
"""

from enum import Enum


class TemplateStatus(str, Enum):
    """工作流模板及版本的生命周期状态。

    DRAFT → ACTIVE：发布后不可修改，需创建新版本。
    ACTIVE → ARCHIVED：归档后不可启动新运行。
    """

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class CapabilityType(str, Enum):
    """平台能力类型，决定运行时如何解析 config_json。"""

    MODEL = "model"
    MCP = "mcp"
    VIRTUAL_MCP = "virtual_mcp"
    FUNCTION = "function"


class ChatbotType(str, Enum):
    """机器人类型。"""

    NORMAL = "normal"
    EMBED = "embed"


class ChatbotStatus(str, Enum):
    """机器人是否对新建会话开放（管理端「启用」开关）。"""

    ACTIVE = "active"
    INACTIVE = "inactive"


class ChatSessionStatus(str, Enum):
    """聊天会话状态。

    ACTIVE：进行中。
    COMPLETED：目标达成或手动关闭。
    EXPIRED：超时自动失效。
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ModelApiMode(str, Enum):
    """模型调用协议，决定运行时使用哪种客户端与模型服务通信。"""

    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK_COMPATIBLE = "deepseek_compatible"
    OPENAI_RESPONSES_COMPATIBLE = "openai_responses_compatible"
    CLAUDE_COMPATIBLE = "claude_compatible"
    GEMINI_COMPATIBLE = "gemini_compatible"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class RoleStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PermissionType(str, Enum):
    """权限的控制粒度类型。

    MENU：菜单可见性控制。
    BUTTON：按钮/操作级控制。
    API：后端接口访问控制。
    """

    MENU = "menu"
    BUTTON = "button"
    API = "api"


class PermissionEffect(str, Enum):
    """直接权限授予的效果，DENY 可覆盖角色继承的 ALLOW。"""

    ALLOW = "allow"
    DENY = "deny"


class NodeMode(str, Enum):
    """节点等待策略标签（历史遗留字段，所有节点均为 session stage）。

    SYNC：节点内 session 不主动发起 wait_callback / wait_timer。
    ASYNC：节点内 session 可能发起外部等待（callback / timer）。
    注意：此枚举仅用于模板级 UI 提示和 async_config 门控，
    不影响运行时执行路径——所有节点统一走 run_session_turn。
    """

    SYNC = "sync"
    ASYNC = "async"


class NodeExecutorType(str, Enum):
    """节点执行器类型。

    AGENT  ：LLM 驱动的 ReAct 会话节点，绑定 model + mcps + functions。
    DIRECT ：历史遗留标签，与 AGENT 行为一致。
    PYTHON ：纯函数节点，由 ``config_json.python_handler`` 指定的 Python
             callable 执行，不需要 LLM，不消耗 token，运行时持有
             ``db_session`` 可直接 :func:`resolve_artifact_refs` 读上游 artifact，
             适合「数据拼装 / 文件落盘 / 多接口批量编排」等纯数据加工活。
    """

    AGENT = "agent"
    DIRECT = "direct"
    PYTHON = "python"


class TaskRunStatus(str, Enum):
    """任务运行整体状态机。

    WAITING：某个节点 session 进入等待（callback / timer），整个运行暂停推进。
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeRunStatus(str, Enum):
    """节点运行状态机。

    WAITING_CALLBACK：节点 session 决定挂起等待（callback 或 timer）。
    TIMEOUT：超时扫描器判定该节点已超时，触发补偿逻辑。
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_CALLBACK = "waiting_callback"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CompensationStatus(str, Enum):
    """节点补偿动作的执行状态。

    SKIPPED：补偿触发条件不满足（如节点未曾执行），跳过补偿。
    """

    NONE = "none"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WakeType(str, Enum):
    """节点 session 被唤醒的原因，用于决定后续逻辑（正常恢复 or 补偿）。

    EXTERNAL：正常收到外部回调。
    TIMEOUT：超时扫描器强制唤醒，通常触发补偿动作。
    """

    EXTERNAL = "external"
    TIMEOUT = "timeout"


class BindingSource(str, Enum):
    """能力绑定的来源范围，用于区分平台级和节点级覆盖。"""

    GLOBAL = "global"
    NODE = "node"


class CompensationActionType(str, Enum):
    """补偿动作的执行方式，对应能力类型的子集。"""

    MCP = "mcp"
    FUNCTION = "function"


class CompensationTrigger(str, Enum):
    """触发补偿的条件。"""

    FAILED = "failed"
    TIMEOUT = "timeout"


class DocumentStatus(str, Enum):
    """知识库文档的处理状态。

    PENDING → PROCESSING → READY：正常流程。
    PROCESSING → FAILED：解析/向量化失败。
    """

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeInjectMode(str, Enum):
    """知识库与工作流节点的集成模式。

    TOOL：注册为 Agent 可调用的检索工具，由 Agent 自主决定何时检索。
    AUTO：自动检索并注入到 system prompt 中，无需 Agent 主动调用。
    """

    TOOL = "tool"
    AUTO = "auto"


class ChunkMethod(str, Enum):
    """文档分块策略。

    FIXED：按固定字数滑动窗口切分（快速，零额外开销）。
    SEMANTIC：基于 embedding 语义相似度变化点切分（效果更好，需调用 embedding API）。
    """

    FIXED = "fixed"
    SEMANTIC = "semantic"
