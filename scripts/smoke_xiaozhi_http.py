"""小智 MCP HTTP 入口冒烟脚本：连上端点，列工具并调用一次。

用法（先以 XIAOZHI_MCP_HTTP_ENABLED=true 启动 api）::

    uv run python scripts/smoke_xiaozhi_http.py [url] [token] [--ask 问题]

不带 --ask 时只做轻量检查（initialize / tools/list / query_task）；
带 --ask 会真实走一轮 agent 问答（需要模型网关可用）。
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _parse_args() -> tuple[str, str, str | None]:
    args = sys.argv[1:]
    question: str | None = None
    if "--ask" in args:
        idx = args.index("--ask")
        question = " ".join(args[idx + 1 :]) or "你好，简单介绍一下你自己"
        args = args[:idx]
    url = args[0] if args else "http://127.0.0.1:8000/agent-flow/xiaozhi/mcp"
    token = args[1] if len(args) > 1 else ""
    return url, token, question


async def main() -> None:
    url, token, question = _parse_args()
    headers = {"Authorization": f"Bearer {token}"} if token else None

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"server: {init.serverInfo.name} {init.serverInfo.version}")

            tools = await session.list_tools()
            print(f"tools: {[t.name for t in tools.tools]}")

            result = await session.call_tool("query_task", {"task_id": 0})
            print(f"query_task -> {getattr(result.content[0], 'text', '')}")

            if question:
                print(f"ask_assistant <- {question}")
                reply = await session.call_tool(
                    "ask_assistant", {"query": question},
                    read_timeout_seconds=None,
                )
                print(f"ask_assistant -> {getattr(reply.content[0], 'text', '')}")


if __name__ == "__main__":
    asyncio.run(main())
