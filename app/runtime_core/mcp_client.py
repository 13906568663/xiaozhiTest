"""MCP transport abstraction.

基于官方 ``mcp`` Python SDK（``mcp.client.streamable_http`` /
``mcp.client.stdio`` + ``mcp.ClientSession``）直接实现：
  * :class:`HttpStatelessMCPClient`
  * :class:`HttpStatefulMCPClient`
  * :class:`StdioStatefulMCPClient`

统一接口：

    class MCPClient:
        async def connect() -> None
        async def list_tools() -> list[mcp.types.Tool]
        async def call_tool(name, arguments) -> mcp.types.CallToolResult
        async def close() -> None
        @property is_stateful: bool
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Mapping, Protocol

logger = logging.getLogger(__name__)


class MCPClient(Protocol):
    name: str
    is_stateful: bool

    async def connect(self) -> None: ...

    async def list_tools(self) -> list[Any]: ...

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None,
    ) -> Any: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# HTTP (streamable_http transport — modern MCP)
# ---------------------------------------------------------------------------


class _HttpClientBase:
    """Common machinery for http_stateless / http_stateful clients."""

    def __init__(
        self,
        *,
        name: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        sse_read_timeout: float = 300.0,
    ) -> None:
        self.name = name
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        self.sse_read_timeout = float(sse_read_timeout)

    async def _open_session(self, stack: AsyncExitStack):
        """Open a streamable_http transport + ClientSession on ``stack``.

        Returns the initialised :class:`mcp.ClientSession`.
        """
        from datetime import timedelta

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        read, write, _ = await stack.enter_async_context(
            streamablehttp_client(
                self.url,
                headers=self.headers or None,
                timeout=timedelta(seconds=self.timeout),
                sse_read_timeout=timedelta(seconds=self.sse_read_timeout),
            )
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session


class HttpStatelessMCPClient(_HttpClientBase):
    is_stateful = False

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[Any]:
        async with AsyncExitStack() as stack:
            session = await self._open_session(stack)
            res = await session.list_tools()
            return list(res.tools)
        return []  # pragma: no cover

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None,
    ) -> Any:
        async with AsyncExitStack() as stack:
            session = await self._open_session(stack)
            return await session.call_tool(name, dict(arguments or {}))


class HttpStatefulMCPClient(_HttpClientBase):
    is_stateful = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return
        stack = AsyncExitStack()
        try:
            session = await self._open_session(stack)
        except Exception:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session

    async def close(self) -> None:
        if self._stack is None:
            return
        try:
            await self._stack.aclose()
        except Exception:
            logger.exception("MCP client %s close failed", self.name)
        finally:
            self._stack = None
            self._session = None

    async def list_tools(self) -> list[Any]:
        await self.connect()
        assert self._session is not None
        res = await self._session.list_tools()
        return list(res.tools)

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None,
    ) -> Any:
        await self.connect()
        assert self._session is not None
        return await self._session.call_tool(name, dict(arguments or {}))


# ---------------------------------------------------------------------------
# Stdio (subprocess) transport
# ---------------------------------------------------------------------------


class StdioStatefulMCPClient:
    is_stateful = True

    def __init__(
        self,
        *,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env or None,
            cwd=self.cwd,
        )
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session

    async def close(self) -> None:
        if self._stack is None:
            return
        try:
            await self._stack.aclose()
        except Exception:
            logger.exception("MCP client %s close failed", self.name)
        finally:
            self._stack = None
            self._session = None

    async def list_tools(self) -> list[Any]:
        await self.connect()
        assert self._session is not None
        res = await self._session.list_tools()
        return list(res.tools)

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None,
    ) -> Any:
        await self.connect()
        assert self._session is not None
        return await self._session.call_tool(name, dict(arguments or {}))


__all__ = [
    "HttpStatefulMCPClient",
    "HttpStatelessMCPClient",
    "MCPClient",
    "StdioStatefulMCPClient",
]
