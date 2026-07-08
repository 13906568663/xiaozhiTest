"""FastAPI 应用入口。

负责组装中间件、路由和应用生命周期钩子。
具体业务逻辑不在此层实现，统一由各域模块（iam / capabilities / workflow）承载。
"""

from __future__ import annotations

import logging
import mimetypes
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.lifecycle import shutdown_event
from app.db.session import init_db
from app.xiaozhi_mcp.connector import build_xiaozhi_service
from app.xiaozhi_mcp.http_entry import XiaozhiHttpEntry


settings = get_settings()

# 尽早配置 root logger：uvicorn 只管自家 logger，业务模块（如小智连接器）
# 的 INFO 日志需要 root handler 才能输出。必须在构建 FastMCP 之前执行——
# FastMCP 构造时也会 basicConfig（它默认把 root 压到自己的 log_level），
# 谁先到谁生效，这里先占住 root 配置权。
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

# 小智 MCP 接入（能力总入口）：按配置组装，未启用时为 None。
# 必须在模块导入期构建——可选的 streamable-http 入口要在 app 定义后立即 mount。
_xiaozhi = build_xiaozhi_service(settings)
_xiaozhi_http: XiaozhiHttpEntry | None = None
if _xiaozhi is not None and settings.xiaozhi_mcp_http_enabled:
    _xiaozhi_http = XiaozhiHttpEntry(
        _xiaozhi.mcp._mcp_server,
        settings.xiaozhi_mcp_http_token,
    )

# StaticFiles 按扩展名猜 Content-Type（mimetypes 模块）。精简版 Linux 容器里
# 没有 /etc/mime.types，.xlsx 等 Office 扩展名猜不出来会回退 text/plain，
# 浏览器（在 nosniff 下）就把二进制当文本渲染成乱码。这里显式注册保证各环境
# 行为一致；重复注册无副作用。
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
)
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
)
mimetypes.add_type("text/csv", ".csv")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # auto_create_tables 仅建议在开发环境开启；生产环境应通过 Alembic 迁移管理表结构
    if settings.auto_create_tables:
        await init_db()
    async with AsyncExitStack() as stack:
        if _xiaozhi is not None:
            # WebSocket 连接循环（后台任务，断线自动重连）
            _xiaozhi.start()
        if _xiaozhi_http is not None:
            # streamable-http 会话管理器要求在应用生命周期内保持运行
            await stack.enter_async_context(_xiaozhi_http.run())
        yield
        # 进入 shutdown 阶段：通知所有长连接（SSE 等）主动结束，
        # 否则 uvicorn 会一直等浏览器关 EventSource 才能退出。
        shutdown_event.set()
        if _xiaozhi is not None:
            await _xiaozhi.stop()


# 统一访问前缀：所有 API / 静态资源 / 接口文档都挂在该前缀下，
# 与前端 NEXT_PUBLIC_BASE_PATH 保持一致，便于 B 系统 nginx 原样反代。
_BASE_PATH = settings.base_path_normalized

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{_BASE_PATH}/docs",
    redoc_url=f"{_BASE_PATH}/redoc",
    openapi_url=f"{_BASE_PATH}/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # 开发环境通过正则同时允许 localhost 的任意端口，避免硬编码每个调试端口
    allow_origin_regex=settings.cors_origin_regex_value,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=f"{_BASE_PATH}{settings.api_prefix}")

# 托管导出文件目录（导出的 xlsx 等），供前端 / 主 AI 直接下载。
# check_dir=False 允许目录尚未创建时也能挂载；首次写入时 handler 会 makedirs。
_exports_dir = Path(settings.exports_dir)
_exports_dir.mkdir(parents=True, exist_ok=True)


class _DownloadStaticFiles(StaticFiles):
    """导出目录专用 StaticFiles：响应加 Content-Disposition: attachment。

    导出文件都是给用户下载的（xlsx 等），强制 attachment 让浏览器始终走
    下载而不是内联渲染——即使某环境 MIME 猜错/代理改头，也不会出现把
    二进制当文本展示成乱码的情况。
    """

    def file_response(self, full_path, stat_result, scope, status_code=200):  # type: ignore[override]
        resp = super().file_response(full_path, stat_result, scope, status_code)
        filename = Path(str(full_path)).name
        from urllib.parse import quote as _quote

        # RFC 5987：filename* 支持非 ASCII 文件名，老浏览器回退 filename
        resp.headers["Content-Disposition"] = (
            f"attachment; filename=\"{_quote(filename)}\"; "
            f"filename*=UTF-8''{_quote(filename)}"
        )
        return resp


app.mount(
    f"{_BASE_PATH}{settings.exports_url_prefix}",
    _DownloadStaticFiles(directory=str(_exports_dir), check_dir=False),
    name="exports",
)

# 可选：把小智元工具同时挂成 streamable-http 端点（{BASE_PATH}/xiaozhi/mcp），
# 供 Cursor / MCP Inspector 等其他 MCP 客户端接入，也便于无设备本地调试。
if _xiaozhi_http is not None:
    app.mount(f"{_BASE_PATH}/xiaozhi/mcp", _xiaozhi_http, name="xiaozhi-mcp")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "Agent Flow Task Scheduler API",
        "docs": "/docs",
    }


def run() -> None:
    """由 pyproject.toml 的 [scripts] 入口调用，用于启动开发服务器。"""
    if sys.platform == "win32" and not settings.api_reload:
        # Windows 非 reload 直跑时 uvicorn 默认建 ProactorEventLoop，psycopg
        # 异步驱动不支持（reload 模式应用在子进程里，uvicorn 自动用 Selector
        # loop，所以只有这条路径需要处理）。这里显式指定 SelectorEventLoop。
        import asyncio

        config = uvicorn.Config(
            "app.main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=False,
        )
        server = uvicorn.Server(config)
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
        return
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )


if __name__ == "__main__":
    run()
