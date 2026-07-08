"""应用生命周期信号。

提供进程级别的 ``shutdown_event``，用于让长连接（SSE / WebSocket /
后台轮询任务）在 uvicorn 优雅关闭时主动结束，而不是等浏览器关闭
EventSource 才被动断开。

典型用法（在长连接生成器里）::

    from app.core.lifecycle import shutdown_event

    async def event_gen():
        while True:
            done, pending = await asyncio.wait(
                {asyncio.create_task(queue.get()),
                 asyncio.create_task(shutdown_event.wait())},
                timeout=15.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if shutdown_event.is_set():
                return
            ...

为什么需要它：

- ``request.is_disconnected()`` 只能感知客户端主动断开，对"服务端
  在 shutdown"无感。
- ``asyncio.Event()`` 在 module 顶层创建即可（Python 3.10+ 不再
  绑定特定 event loop），首次 ``set/wait`` 时延迟绑定到当前 loop。

注意：``--reload`` 热重载会启动新进程并新建 Event，所以热重载场景下
旧 Event 不会被复用，没有跨进程一致性问题。
"""

from __future__ import annotations

import asyncio


shutdown_event: asyncio.Event = asyncio.Event()


__all__ = ["shutdown_event"]
