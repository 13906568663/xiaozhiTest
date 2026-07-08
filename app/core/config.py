"""全局配置模块。

通过 pydantic-settings 从 .env 文件和环境变量读取配置。
所有模块应通过 get_settings() 单例获取配置，避免重复解析环境变量。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


# 定位到项目根目录，使 .env 的路径与工作目录无关
ROOT_DIR = Path(__file__).resolve().parents[2]

# 把 .env 同步进程环境变量（不覆盖已有系统变量）：pydantic-settings 只把
# .env 读进 Settings 字段，而模型能力的 api_key_env（密钥经环境变量引用、
# 避免明文入库）走 os.getenv，需要 .env 中的自定义键也进 os.environ。
load_dotenv(ROOT_DIR / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        # 允许 .env 中包含未声明的变量，不抛出校验错误
        extra="ignore",
    )

    app_name: str = "Agent Flow Task Scheduler"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True

    # 统一访问前缀：B 系统通过 nginx 反代我们的前后端时，所有接口/资源/文档
    # 都挂在此前缀下（nginx 原样 proxy_pass，无需 rewrite）。前端需同步配置
    # NEXT_PUBLIC_BASE_PATH 为相同值。可含多级路径（如 /wgzcb-jzdd-dx/api/agent-flow）。
    # 置空字符串则不加前缀（本地开发可关闭）。
    base_path: str = "/agent-flow"

    database_url: str = "postgresql+psycopg://root:root@localhost:5432/agent_flow"
    database_echo: bool = False
    # 生产环境应设为 False，改用 Alembic 做受控迁移
    auto_create_tables: bool = False

    # 仅当数据库为空时（首次启动）用于创建引导管理员账号
    admin_username: str = "platform_admin"
    admin_password: str = "TaskFlow2026!Console"
    admin_display_name: str = "Platform Admin"
    # 用于 HMAC-SHA256 签名 JWT，生产环境务必替换为足够长的随机字符串
    auth_secret_key: str = "agent-flow-dev-secret"
    auth_access_token_ttl_hours: int = 12
    auth_cookie_name: str = "agent_flow_session"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    default_model_name: str = "gpt-5.2"

    # 多个源站用逗号分隔，例如 "https://app.example.com,https://admin.example.com"
    cors_origins: str = "http://localhost:3000"
    cors_origin_regex: str | None = None
    log_level: str = "INFO"

    # ===== 工具调用日志埋点（外部 API 调用统计能力的数据源）=====
    # 关闭时，POST_ACTING hook 整体跳过 tool_call_log 写入，不影响业务主流程。
    # 紧急情况（如表写满 / 索引膨胀）下可临时置 False 关闭埋点。
    tool_call_log_enabled: bool = True
    # 单条日志的 arguments_json / response_preview 截断上限，防止超大 payload
    # 撑爆表。response_preview 截到字符数；arguments_json 不截断键值数，但
    # 序列化结果超过此长度会整体置 ``{"_truncated": true}``。
    tool_call_log_arguments_max_chars: int = 4000
    tool_call_log_response_preview_max_chars: int = 2000
    tool_call_log_error_message_max_chars: int = 1000

    # ===== 小智AI MCP 接入点（对外暴露平台能力的 MCP 总入口）=====
    # 开关：为 True 且 endpoint 非空时，lifespan 启动 WebSocket 连接器，
    # 反向接入小智云端（我们拨出连接，小智在连接上作为 MCP 客户端调用工具）。
    xiaozhi_mcp_enabled: bool = False
    # 从 xiaozhi.me 控制台"智能体 → 配置角色"页获取，形如
    # wss://api.xiaozhi.me/mcp/?token=xxx
    xiaozhi_mcp_endpoint: str = ""
    # 绑定的平台机器人 ID：小智传来的语音请求整体路由到该机器人的 ChatEngine
    #（完整 ReAct：技能 / 知识库 / 记忆 / 外部 MCP 工具）。
    xiaozhi_chatbot_id: str = ""
    # ask_assistant 同步等待上限：小智云端工具调用超时较短，超过该秒数自动
    # 转为后台任务并立即返回"处理中"提示，用户可稍后追问结果。
    xiaozhi_sync_timeout_seconds: float = 20.0
    # 会话粘滞：距上次对话空闲超过该分钟数后，下一句话自动开新的平台会话
    #（旧会话仍在库里，跨会话记忆由 memory 模块承接）。
    xiaozhi_session_idle_minutes: int = 30
    # 返回给小智的文本长度上限（超出截断），语音播报场景防 TTS 爆炸。
    xiaozhi_reply_max_chars: int = 800
    # 可选：把同一套元工具挂成 streamable-http 端点（{BASE_PATH}/xiaozhi/mcp），
    # 供 Cursor / MCP Inspector 等其他 MCP 客户端使用，也方便无小智设备时本地调试。
    xiaozhi_mcp_http_enabled: bool = False
    # HTTP 入口的访问令牌：非空时要求 Authorization: Bearer <token>；
    # 留空则不鉴权（仅限本机/内网调试，勿在公网放开）。
    xiaozhi_mcp_http_token: str = ""

    # ===== 导出文件静态托管 =====
    # exports_dir 是后端写导出文件的本地目录（相对项目根 / 进程工作目录）；
    # exports_url_prefix 是 main.py 把该目录 mount 成静态资源的 URL 前缀。
    exports_dir: str = "output/final"
    exports_url_prefix: str = "/static/exports"
    # 导出文件下载链接的绝对地址前缀（后端对外可访问的 host，如
    # http://localhost:8000 或正式环境后端域名）；留空则只返回相对路径（同源访问够用）。
    exports_download_base_url: str = ""

    @property
    def base_path_normalized(self) -> str:
        """归一化前缀：去除尾部斜杠；非空时确保以 ``/`` 开头。空表示不加前缀。"""
        bp = self.base_path.strip().rstrip("/")
        if not bp:
            return ""
        return bp if bp.startswith("/") else f"/{bp}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def cors_origin_regex_value(self) -> str | None:
        # 显式配置优先；开发环境自动允许本地所有端口，无需在 cors_origins 中逐一列举
        if self.cors_origin_regex:
            return self.cors_origin_regex
        if self.app_env == "development":
            return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
        return None


@lru_cache
def get_settings() -> Settings:
    """返回全局唯一的 Settings 实例（进程级缓存）。"""
    return Settings()
