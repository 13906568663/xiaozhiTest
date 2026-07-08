"""小智侧工具面：FastMCP 元工具定义。

只暴露 3 个稳定工具，小智云端的 LLM 负责决定何时调用：

  - ask_assistant  同步问答（限时等待，超时自动降级为后台任务）
  - submit_task    显式提交长任务（立即返回编号）
  - query_task     查询任务进度 / 结果

所有工具都返回纯文本：结果会被小智的大模型转述后语音播报，文本比
JSON 结构更不容易被读错；错误也以正常文本返回（不抛异常），避免小智
端把 traceback 播报给用户。
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

import asyncio

from app.core.config import Settings, get_settings
from app.xiaozhi_mcp.agent_proxy import AgentProxy, XiaozhiAgentError
from app.xiaozhi_mcp.tasks import TaskBoard, TaskRecord

logger = logging.getLogger("app.xiaozhi_mcp.server")

_INSTRUCTIONS = (
    "这是 agent-flow 平台的能力总入口。平台上运行着一个功能完整的智能体"
    "（可使用技能、知识库、长期记忆和外部工具）。遇到你自己无法直接回答的"
    "问题、需要查资料 / 操作系统 / 执行多步骤任务时，把用户的原话交给"
    " ask_assistant；明确的耗时任务用 submit_task 提交，之后用 query_task"
    " 查询结果。"
)


def build_mcp_server(
    proxy: AgentProxy,
    board: TaskBoard,
    settings: Settings | None = None,
) -> FastMCP:
    """组装 FastMCP 实例（工具以闭包形式绑定 proxy / board）。"""
    cfg = settings or get_settings()

    mcp = FastMCP(
        name="agent-flow",
        instructions=_INSTRUCTIONS,
        # 供可选的 streamable-http 挂载复用；WebSocket 桥接不读这两项
        stateless_http=True,
        log_level="WARNING",
    )

    # ------------------------------------------------------------------
    # 工具 1：同步问答（超时降级）
    # ------------------------------------------------------------------

    # structured_output=False：只回纯文本 content，不带 outputSchema /
    # structuredContent，对小智端的简易 MCP 客户端兼容性最好。
    @mcp.tool(
        name="ask_assistant",
        description=(
            "向后台智能体提问或下达指令。它能使用技能、知识库、长期记忆和"
            "外部工具，适合回答需要查询资料或执行操作的请求。把用户的诉求"
            "原样完整转述（不要缩写省略）。若处理时间较长，会自动转为后台"
            "任务并返回任务编号，届时告知用户稍后询问结果即可。"
        ),
        structured_output=False,
    )
    async def ask_assistant(
        query: Annotated[
            str,
            Field(description="用户的问题或指令，保留完整上下文信息"),
        ],
    ) -> str:
        query = (query or "").strip()
        if not query:
            return "问题内容为空，请把用户的原话传进来。"

        sync_budget = cfg.xiaozhi_sync_timeout_seconds
        if sync_budget <= 0:
            sync_budget = 20.0
        agent_task = asyncio.create_task(proxy.ask(query))
        done, _pending = await asyncio.wait({agent_task}, timeout=sync_budget)
        if agent_task in done:
            return _collect_result(agent_task)

        # 超时：不取消，收编为后台任务继续跑
        record = board.adopt(agent_task, description=query, kind="问答")
        logger.info("ask_assistant 超时降级为后台任务 %s：%s", record.task_id, query[:80])
        return (
            f"这个请求处理时间较长，已转为后台任务（编号 {record.task_id}）继续执行。"
            "请告诉用户稍等片刻，然后再问我要结果。"
        )

    # ------------------------------------------------------------------
    # 工具 2：显式异步任务
    # ------------------------------------------------------------------

    @mcp.tool(
        name="submit_task",
        description=(
            "提交一个明确耗时的后台任务（如整理报告、批量查询、多步骤操作），"
            "立即返回任务编号，不阻塞对话。任务描述必须自包含：把用户提到的"
            "所有要求、对象、限制条件都写进去，因为后台执行时看不到当前对话。"
        ),
        structured_output=False,
    )
    async def submit_task(
        task: Annotated[
            str,
            Field(description="完整自包含的任务描述，包含全部必要细节"),
        ],
    ) -> str:
        task = (task or "").strip()
        if not task:
            return "任务描述为空，请把要做的事情完整描述后再提交。"
        record = board.submit(proxy.run_isolated(task), description=task)
        logger.info("submit_task 登记后台任务 %s：%s", record.task_id, task[:80])
        return (
            f"任务已提交，编号 {record.task_id}，正在后台执行。"
            "请告诉用户稍后可以问我任务结果。"
        )

    # ------------------------------------------------------------------
    # 工具 3：任务查询
    # ------------------------------------------------------------------

    @mcp.tool(
        name="query_task",
        description=(
            "查询后台任务的进度和结果。用户追问'刚才的任务怎么样了 / 结果出来"
            "了吗'时调用；不确定编号就不填，默认查最近一个任务。"
        ),
        structured_output=False,
    )
    async def query_task(
        task_id: Annotated[
            int,
            Field(description="任务编号；不知道编号时填 0，表示查最近一个任务"),
        ] = 0,
    ) -> str:
        record = board.get(task_id) if task_id > 0 else board.latest()
        if record is None:
            if task_id > 0:
                return f"没有找到编号 {task_id} 的任务，可能已过期清理。"
            return "当前没有任何后台任务记录。"
        return _describe_record(record)

    return mcp


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------


def _collect_result(agent_task: "asyncio.Task[str]") -> str:
    """取回已完成 agent 轮次的结果，异常统一转成可播报文本。"""
    try:
        return agent_task.result()
    except XiaozhiAgentError as exc:
        return str(exc)
    except Exception:
        logger.exception("小智问答执行失败")
        return "后台处理出错了，请稍后再试。"


def _describe_record(record: TaskRecord) -> str:
    if record.status == "running":
        elapsed = int(time.time() - record.created_at.timestamp())
        return (
            f"{record.kind}（编号 {record.task_id}）仍在处理中，已运行约 {elapsed} 秒。"
            "请告诉用户再稍等一会儿。"
        )
    if record.status == "failed":
        return f"{record.kind}（编号 {record.task_id}）执行失败：{record.error}"
    return f"{record.kind}（编号 {record.task_id}）已完成，结果如下：\n{record.result}"
