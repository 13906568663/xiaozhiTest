"""小智接入服务的组装与生命周期管理。

XiaozhiService 把 proxy / board / FastMCP 组装成一个整体，供 main.py：
  - 在 lifespan 启动时 start()（拉起 WebSocket 连接循环后台任务）；
  - 在 shutdown 时 stop()（断开连接、取消后台任务）；
  - 可选地把 mcp.streamable_http_app() 挂载为 HTTP 入口（其他 MCP 客户端
    / 本地调试用，无需小智设备）。

重连策略：指数退避 1s -> 2s -> ... -> 60s 封顶；一次连接存活超过 60s
视为曾经健康，退避归零重新计。
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import Settings, get_settings
from app.xiaozhi_mcp.agent_proxy import AgentProxy, XiaozhiAgentError
from app.xiaozhi_mcp.bridge import serve_connection
from app.xiaozhi_mcp.server import build_mcp_server
from app.xiaozhi_mcp.tasks import TaskBoard

logger = logging.getLogger("app.xiaozhi_mcp.connector")

_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 60.0
# 连接存活超过该秒数后，下次断开从最小退避重新开始
_HEALTHY_CONNECTION_SECONDS = 60.0


class XiaozhiService:
    """小智 MCP 接入的进程内单例（由 main.py 持有）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.proxy = AgentProxy(self.settings)
        self.board = TaskBoard()
        self.mcp = build_mcp_server(self.proxy, self.board, self.settings)
        self._loop_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def websocket_enabled(self) -> bool:
        return bool(
            self.settings.xiaozhi_mcp_enabled
            and self.settings.xiaozhi_mcp_endpoint.strip()
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """拉起 WebSocket 连接循环（未启用则空操作）。"""
        if not self.websocket_enabled:
            if self.settings.xiaozhi_mcp_enabled:
                logger.warning(
                    "XIAOZHI_MCP_ENABLED=true 但 XIAOZHI_MCP_ENDPOINT 为空，跳过小智接入"
                )
            return
        if self._loop_task is not None:
            return
        self._stopping.clear()
        self._loop_task = asyncio.create_task(
            self._run_forever(), name="xiaozhi-mcp-connector"
        )
        logger.info("小智 MCP 连接器已启动")

    async def stop(self) -> None:
        """优雅停止：断开连接、结束重连循环、取消后台任务。"""
        self._stopping.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except BaseException:
                # shutdown 阶段全部吞掉：CancelledError / 连接异常 / anyio
                # 任务组包装的 BaseExceptionGroup 都不应阻断进程退出
                pass
            self._loop_task = None
        await self.board.shutdown()
        logger.info("小智 MCP 连接器已停止")

    # ------------------------------------------------------------------
    # 连接循环
    # ------------------------------------------------------------------

    async def _run_forever(self) -> None:
        await self._log_binding()
        endpoint = self.settings.xiaozhi_mcp_endpoint.strip()
        backoff = _BACKOFF_INITIAL

        while not self._stopping.is_set():
            connected_at = time.monotonic()
            try:
                await serve_connection(self.mcp, endpoint)
                logger.warning("小智接入点连接已关闭")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("小智接入点连接异常：%s", exc)

            if self._stopping.is_set():
                return

            if time.monotonic() - connected_at >= _HEALTHY_CONNECTION_SECONDS:
                backoff = _BACKOFF_INITIAL
            logger.info("%.0f 秒后重连小智接入点", backoff)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=backoff)
                return  # stop() 提前唤醒
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, _BACKOFF_MAX)

    async def _log_binding(self) -> None:
        """启动自检：绑定配置有问题只告警不中断（工具调用时会给用户可读提示）。"""
        try:
            bot_name = await self.proxy.describe_bot()
            logger.info("小智 MCP 已绑定机器人：%s", bot_name)
        except XiaozhiAgentError as exc:
            logger.error("小智 MCP 机器人绑定异常：%s", exc)
        except Exception:
            logger.exception("小智 MCP 启动自检失败（数据库不可用？）")


def build_xiaozhi_service(settings: Settings | None = None) -> XiaozhiService | None:
    """按配置决定是否组装小智服务：WebSocket 接入与 HTTP 入口都关闭时返回 None。"""
    cfg = settings or get_settings()
    if cfg.xiaozhi_mcp_enabled or cfg.xiaozhi_mcp_http_enabled:
        return XiaozhiService(cfg)
    return None
