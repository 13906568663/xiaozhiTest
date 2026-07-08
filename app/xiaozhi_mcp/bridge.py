"""WebSocket 出站桥接：在"我们拨出的连接"上运行 MCP Server。

小智接入点的连接方向与常规 MCP 部署相反：传输层上我们是 WebSocket
客户端（主动 connect 到 wss://api.xiaozhi.me/mcp/?token=xxx），但 MCP
协议层上我们是 Server（小智云端发 initialize / tools/list / tools/call）。

官方 SDK 只提供"作为服务端监听 WebSocket"或"作为客户端拨出"两种组合，
没有"拨出连接上跑 Server"的现成传输，这里参照 mcp.client.websocket 的
实现自建：每个 WebSocket 文本帧就是一条 JSON-RPC 消息，通过 anyio 内存
流对接低层 Server 的读写口。

连接断开的传导路径：ws 关闭 -> ``async for`` 迭代结束 -> read_stream
关闭 -> Server.run() 的消息循环结束返回 -> serve_connection 抛出/返回，
由 connector 决定重连。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError
from websockets.asyncio.client import connect as ws_connect

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage

logger = logging.getLogger("app.xiaozhi_mcp.bridge")

ReadStream = MemoryObjectReceiveStream[SessionMessage | Exception]
WriteStream = MemoryObjectSendStream[SessionMessage]


@asynccontextmanager
async def outbound_websocket_transport(
    url: str,
) -> AsyncIterator[tuple[ReadStream, WriteStream]]:
    """拨出 WebSocket 连接并暴露 (read_stream, write_stream) 给 MCP Server。

    不请求 "mcp" 子协议：小智服务端不做子协议协商（官方 mcp_pipe.py 也是
    裸连接），请求了反而可能握手失败。
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        SessionMessage
    ](0)

    # websockets 默认每 20s 发协议层 ping，保活 NAT / 反代空闲超时
    async with ws_connect(url, max_size=4 * 1024 * 1024) as ws:

        async def ws_reader() -> None:
            async with read_stream_writer:
                async for raw in ws:
                    text = raw if isinstance(raw, str) else raw.decode("utf-8")
                    try:
                        message = types.JSONRPCMessage.model_validate_json(text)
                        await read_stream_writer.send(SessionMessage(message))
                    except ValidationError as exc:
                        # 非法消息不掐断连接，交给 Server 的异常分支记日志
                        await read_stream_writer.send(exc)

        async def ws_writer() -> None:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    payload = session_message.message.model_dump(
                        by_alias=True, mode="json", exclude_none=True
                    )
                    await ws.send(json.dumps(payload, ensure_ascii=False))

        async with anyio.create_task_group() as tg:
            tg.start_soon(ws_reader)
            tg.start_soon(ws_writer)
            try:
                yield read_stream, write_stream
            finally:
                tg.cancel_scope.cancel()


async def serve_connection(mcp: FastMCP, url: str) -> None:
    """维持一条到小智接入点的连接并在其上服务 MCP，直到连接断开。

    正常断开时返回；网络/握手异常向上抛，由 connector 统一按"断线"处理。
    """
    lowlevel = mcp._mcp_server
    async with outbound_websocket_transport(url) as (read_stream, write_stream):
        logger.info("已连接小智接入点，MCP 服务就绪")
        await lowlevel.run(
            read_stream,
            write_stream,
            lowlevel.create_initialization_options(),
            # 工具内部已兜底异常；此处 False 让协议层错误以 JSON-RPC error 回给对端
            raise_exceptions=False,
        )
