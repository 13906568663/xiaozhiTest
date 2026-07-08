# agent-flow

智能体（Agent）平台：自研 agent runtime + 对话机器人管理，仿 Claude Code 的
ReAct 循环 / 上下文压缩 / 技能（SKILL.md）机制。

技术栈：

- 后端：FastAPI + PostgreSQL(pgvector) + 自研 agent runtime（`app/runtime_core`）
- 前端：Next.js

## 功能范围

**智能体核心**

- `app/runtime_core` — 自研 agent 运行时：
  - `runtime.py`：ReAct 循环（流式、finish-tool 结构化出口、tool_use/result 配对修复、
    只读工具并行执行、token usage 记账）
  - `compression.py`：Claude Code 风格上下文压缩（两段式摘要、真实 usage 触发、
    超大工具结果截断、多次压缩合并、规则兜底）
  - `provider.py`：OpenAI 兼容 provider（流式、国内网关自适应重试、TokenUsage）
  - `tool_protocol.py`：工具注册表（function / MCP 双通道、并行安全标记）
  - `plan.py`：PlanNotebook 计划工具（类 TodoWrite）
  - `memory.py` / `messages.py` / `formatter.py` / `hooks.py` / `mcp_client.py`
- `app/chatbot` — 对话产品面：机器人 CRUD、会话/消息、SSE 流式对话、公开链接对话、
  会话管理后台、目标判定、会话记忆持久化、工具调用日志
- `app/workflow`（runtime 底座）— chatbot 的执行支撑：能力绑定解析
  （`capability_resolver`）、工具注册（`tool_registry`）、大结果 artifact 剥离
  （`session_assets`，`node_run_artifact` 表）
- `app/capabilities` — 能力注册表：模型 Provider / MCP 服务
- `app/skill` — SKILL.md 技能（渐进式加载：索引进 prompt，正文按需 `load_skill`）
- `app/knowledge` — 知识库 RAG（pgvector 向量检索，绑定到机器人后以检索工具形式暴露）
- `app/memory` — 用户跨会话记忆
- `app/iam` — 登录鉴权、用户/角色/权限、API Key
- `app/xiaozhi_mcp` — 小智AI MCP 接入（能力总入口）：反向 WebSocket 接入
  xiaozhi.me 接入点，只暴露 3 个元工具（`ask_assistant` / `submit_task` /
  `query_task`），把语音请求整体路由到绑定机器人的 ChatEngine；支持同步
  问答超时自动降级为后台任务、会话粘滞、断线指数退避重连；可选把同一套
  工具挂成 streamable-http（`{BASE_PATH}/xiaozhi/mcp`）供其他 MCP 客户端使用

## 目录结构

```text
.
├── alembic/                 # 数据库迁移
├── app/
│   ├── api/                 # 路由聚合 / 依赖（认证）
│   ├── capabilities/        # 模型 / MCP 能力注册
│   ├── chatbot/             # 对话机器人（引擎编排 + 路由）
│   ├── core/                # 配置 / 生命周期
│   ├── db/                  # SQLAlchemy models / session
│   ├── domain/              # 枚举与权限定义
│   ├── iam/                 # 认证与用户体系
│   ├── knowledge/           # 知识库 RAG
│   ├── memory/              # 用户记忆
│   ├── runtime_core/        # 自研 agent runtime（核心）
│   ├── skill/               # SKILL.md 技能
│   ├── workflow/            # runtime 底座（能力解析 / 工具注册 / artifact）
│   └── main.py              # FastAPI 入口
├── tests/backend/
├── web/                     # Next.js 前端
└── pyproject.toml
```

## 环境变量

根目录 `.env` 是后端默认环境文件，模板见 `.env.example`。关键变量：

```env
DATABASE_URL=postgresql+psycopg://root:root@localhost:5432/agent_flow
AUTO_CREATE_TABLES=true          # 开发环境自动建表；生产用 Alembic
BASE_PATH=/agent-flow            # 统一访问前缀（nginx 反代用），置空则不加前缀
ADMIN_USERNAME=platform_admin
ADMIN_PASSWORD=TaskFlow2026!Console
AUTH_SECRET_KEY=agent-flow-dev-secret
OPENAI_API_KEY=sk-...            # 全局兜底模型 Key（能力注册表可按模型单独配）
```

本地 PostgreSQL 可用 Docker 一键起（带 pgvector，与上面 DATABASE_URL 匹配）：

```bash
docker run -d --name agent-flow-pg --restart unless-stopped \
  -e POSTGRES_USER=root -e POSTGRES_PASSWORD=root -e POSTGRES_DB=agent_flow \
  -p 5432:5432 -v agent_flow_pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```

### 小智AI MCP 接入（能力总入口）

把平台完整 agent 能力通过 MCP 暴露给小智AI语音终端：

```env
XIAOZHI_MCP_ENABLED=true
XIAOZHI_MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=...   # xiaozhi.me 控制台获取
XIAOZHI_CHATBOT_ID=<平台机器人ID>                           # 语音请求路由到该机器人
XIAOZHI_SYNC_TIMEOUT_SECONDS=20   # 同步等待上限，超时自动转后台任务
XIAOZHI_SESSION_IDLE_MINUTES=30   # 会话粘滞空闲上限，超时开新会话
XIAOZHI_REPLY_MAX_CHARS=800       # 语音回复截断上限
XIAOZHI_MCP_HTTP_ENABLED=false    # 可选：{BASE_PATH}/xiaozhi/mcp 调试入口
XIAOZHI_MCP_HTTP_TOKEN=           # HTTP 入口 Bearer Token（留空不鉴权，仅限内网）
```

接入步骤：xiaozhi.me 控制台复制接入点 → 填 `.env` → 平台建一个"语音助手"
机器人（提示词写明简短口语化）并把 ID 填入 → 重启 api → 控制台刷新可见
`ask_assistant` / `submit_task` / `query_task` 三个工具。无小智设备时可开
HTTP 入口用 `uv run python scripts/smoke_xiaozhi_http.py` 冒烟验证。

前端如需显式指定 API 地址，在 `web/.env.local` 配置：

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/agent-flow/api/v1
NEXT_PUBLIC_BASE_PATH=/agent-flow
```

## 后端开发

```bash
uv sync          # 安装依赖
uv run api       # 启动 API（默认 http://127.0.0.1:8000）
uv run pytest    # 运行测试
```

接口文档：`http://127.0.0.1:8000/agent-flow/docs`（跟随 BASE_PATH）。

除 `GET /healthz`、`POST .../auth/login` 和公开对话 `.../chat/public/*`
（access_token 鉴权）外，其余接口都要求 Bearer token / Cookie。

## 数据库迁移

```bash
uv run alembic upgrade head                            # 升级到最新
uv run alembic revision --autogenerate -m "message"    # 模型变更后生成新迁移
```

本地此前用 `AUTO_CREATE_TABLES=true` 自动建过表、无 revision 记录的库，先执行
`uv run alembic stamp head`。

## 前端开发

```bash
pnpm install
pnpm --dir web dev    # http://127.0.0.1:3000
```

页面结构（登录后默认进入对话消息）：

```text
/login                    登录
/chat/messages            对话消息（发起会话/查看历史）
/chat/config              对话配置（机器人 CRUD、能力绑定）
/chat-console/[id]        机器人调试台
/capabilities/mcp         MCP 工具注册
/skills                   技能管理（SKILL.md）
/knowledge/bases          知识库管理
/admin/models             模型管理
/admin/memory             记忆管理
/admin/sessions           会话管理
/iam/users|roles|permissions  用户/角色/权限
/profile                  个人资料 / API Key
```

## 主要 API

- 认证：`POST /auth/login`、`GET /auth/me`、`POST /auth/logout`
- 机器人：`GET|POST /chatbots`、`GET|PUT|DELETE /chatbots/{id}`
- 对话：`POST /chat/sessions`、`GET /chat/sessions/{id}/messages`、
  `POST /chat/sessions/{id}/messages/stream`（SSE）
- 公开对话：`GET|POST /chat/public/{access_token}/...`
- 能力：`GET|POST /capabilities`、`GET|PUT|DELETE /capabilities/{id}`
- 技能 / 知识库 / 记忆 / 用户体系：`/skills`、`/knowledge-bases`、`/memories`、
  `/users`、`/roles`、`/permissions`、`/profile`

完整清单见 `/docs`（OpenAPI）。
