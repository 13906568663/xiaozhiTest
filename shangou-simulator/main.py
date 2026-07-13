"""闪购外卖派单模拟系统入口。

启动:cd shangou-simulator && uv sync && uv run python main.py
- 管理后台:  http://127.0.0.1:18100/
- MCP 接入点: http://127.0.0.1:18100/mcp (streamable-http)
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from shangou_sim.api import build_router
from shangou_sim.clock import SimClock
from shangou_sim.mcp_tools import build_mcp
from shangou_sim.store import Store

HOST = os.getenv("SIM_HOST", "127.0.0.1")
PORT = int(os.getenv("SIM_PORT", "18100"))
TIME_SCALE = float(os.getenv("SIM_TIME_SCALE", "5"))

STATIC_DIR = Path(__file__).parent / "shangou_sim" / "static"

store = Store(SimClock(scale=TIME_SCALE))
mcp = build_mcp(store)
mcp_app = mcp.streamable_http_app()


async def _autogen_loop() -> None:
    while True:
        await asyncio.sleep(1)
        store.autogen_tick()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_autogen_loop())
    async with mcp.session_manager.run():
        yield
    task.cancel()


app = FastAPI(title="闪购外卖派单模拟系统", lifespan=lifespan)
app.include_router(build_router(store), prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# 挂在最后作为兜底路由:未被上面路由匹配的请求(即 /mcp)交给 MCP 子应用
app.mount("/", mcp_app)


def run() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    run()
