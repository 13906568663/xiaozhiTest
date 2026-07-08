"""可选 HTTP 入口：streamable-http 端点（带简易 Bearer Token 门卫）。

不直接用 FastMCP.streamable_http_app()：它内部的 StreamableHTTPSessionManager
每个实例只允许 run() 一次，而应用 lifespan 可能多次启停（TestClient、
测试夹具等场景），第二次 startup 就会炸。这里自持一个 ASGI 端点，每次
lifespan 启动时重建 manager。

鉴权：该端点绕过平台 IAM（MCP 客户端不会带平台 JWT / API Key），配置了
XIAOZHI_MCP_HTTP_TOKEN 时要求 ``Authorization: Bearer <token>`` 完全匹配，
未配置则直接放行（仅限本机/内网调试场景）。
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


class XiaozhiHttpEntry:
    """挂载到 FastAPI 的 ASGI 端点；manager 生命周期由 run() 管理。"""

    def __init__(self, lowlevel_server: Server[Any, Any], token: str = "") -> None:
        self._server = lowlevel_server
        self._token = token.strip()
        self._manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """在应用 lifespan 内保持 session manager 运行（每次启动新建实例）。"""
        manager = StreamableHTTPSessionManager(
            app=self._server,
            event_store=None,
            json_response=False,
            # 无状态模式：每个请求独立初始化，工具型入口无需跨请求会话
            stateless=True,
        )
        async with manager.run():
            self._manager = manager
            try:
                yield
            finally:
                self._manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            raise RuntimeError(f"不支持的 scope 类型: {scope['type']}")

        if self._token and not self._authorized(scope):
            await JSONResponse({"detail": "unauthorized"}, status_code=401)(
                scope, receive, send
            )
            return

        manager = self._manager
        if manager is None:
            await JSONResponse({"detail": "mcp endpoint not ready"}, status_code=503)(
                scope, receive, send
            )
            return
        await manager.handle_request(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        auth = headers.get(b"authorization", b"").decode("utf-8", "replace")
        return hmac.compare_digest(auth, f"Bearer {self._token}")
