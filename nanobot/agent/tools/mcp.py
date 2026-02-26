"""MCP (Model Context Protocol) tool adapter and lifecycle manager."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool


def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    """Read config value from either dict or object-style configs."""
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


class MCPTool(Tool):
    """Wrap a single MCP server tool as a nanobot Tool."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        session: Any,
        tool_timeout: int = 30,
    ):
        self._server_name = server_name
        self._tool_name = tool_name
        self._tool_description = tool_description
        self._input_schema = input_schema
        self._session = session
        self._tool_timeout = max(1, int(tool_timeout))

    @property
    def name(self) -> str:
        return f"mcp__{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._tool_description}"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._tool_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "MCP tool '{}:{}' timed out after {}s",
                self._server_name,
                self._tool_name,
                self._tool_timeout,
            )
            return f"MCP Error ({self._server_name}/{self._tool_name}): timed out after {self._tool_timeout}s"
        except Exception as e:
            return f"MCP Error ({self._server_name}/{self._tool_name}): {e}"

        parts: list[str] = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
                continue
            text = getattr(block, "text", None)
            parts.append(text if isinstance(text, str) else str(block))
        return "\n".join(parts) if parts else "(empty result)"


class _ServerHandle:
    """Holds runtime state for one MCP server connection."""

    def __init__(self, name: str):
        self.name = name
        self.task: asyncio.Task[None] | None = None
        self.session: Any = None
        self.tools: list[MCPTool] = []
        self.stop_event = asyncio.Event()


class MCPManager:
    """Manage lifecycle of MCP server connections."""

    def __init__(self, servers: dict[str, Any]):
        self._configs: dict[str, Any] = {}
        for name, cfg in servers.items():
            if not _cfg_get(cfg, "enabled", True):
                continue
            self._configs[name] = cfg
        self._handles: list[_ServerHandle] = []

    @property
    def server_names(self) -> list[str]:
        return [h.name for h in self._handles]

    async def start(self) -> list[MCPTool]:
        """Connect all configured MCP servers and return discovered tools."""
        all_tools: list[MCPTool] = []
        loop = asyncio.get_running_loop()

        for name, cfg in self._configs.items():
            handle = _ServerHandle(name)
            ready: asyncio.Future[None] = loop.create_future()
            handle.task = asyncio.create_task(self._run_server(name, cfg, handle, ready))

            try:
                await asyncio.wait_for(ready, timeout=30)
                self._handles.append(handle)
                all_tools.extend(handle.tools)
                logger.info("MCP server '{}': {} tools discovered", name, len(handle.tools))
            except (asyncio.TimeoutError, BaseException) as e:
                if isinstance(e, asyncio.TimeoutError):
                    logger.error("MCP server '{}': connection timed out (30s)", name)
                else:
                    logger.error("MCP server '{}': failed to connect: {}", name, e)
                if handle.task and not handle.task.done():
                    handle.task.cancel()
                    try:
                        await handle.task
                    except (asyncio.CancelledError, BaseException):
                        pass

        return all_tools

    async def stop(self) -> None:
        """Signal all server tasks to stop and wait for cleanup."""
        for handle in reversed(self._handles):
            handle.stop_event.set()
            if handle.task:
                try:
                    await asyncio.wait_for(handle.task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError, BaseException):
                    if handle.task and not handle.task.done():
                        handle.task.cancel()
                        try:
                            await handle.task
                        except (asyncio.CancelledError, BaseException):
                            pass
        self._handles.clear()

    async def _run_server(
        self,
        name: str,
        cfg: Any,
        handle: _ServerHandle,
        ready: asyncio.Future[None],
    ) -> None:
        """Run one MCP connection task and keep it alive until stop is requested."""
        from mcp import ClientSession

        try:
            cm_transport = self._create_transport(cfg)
            async with cm_transport as transport_result:
                if isinstance(transport_result, tuple) and len(transport_result) >= 2:
                    read_stream, write_stream = transport_result[0], transport_result[1]
                else:
                    read_stream, write_stream = transport_result, None

                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    handle.session = session

                    result = await session.list_tools()
                    tool_timeout = int(_cfg_get(cfg, "tool_timeout", 30))
                    for tool in result.tools:
                        input_schema = getattr(tool, "inputSchema", None) or {
                            "type": "object",
                            "properties": {},
                        }
                        handle.tools.append(
                            MCPTool(
                                server_name=name,
                                tool_name=tool.name,
                                tool_description=tool.description or tool.name,
                                input_schema=input_schema,
                                session=session,
                                tool_timeout=tool_timeout,
                            )
                        )

                    if not ready.done():
                        ready.set_result(None)

                    await handle.stop_event.wait()

        except BaseException as e:
            if not ready.done():
                ready.set_exception(e)
            else:
                logger.warning("MCP server '{}': connection lost: {}", name, e)

    @staticmethod
    def _create_transport(cfg: Any) -> Any:
        """Create transport context manager based on MCP server config."""
        transport = str(_cfg_get(cfg, "transport", "") or "").strip().lower()
        command = _cfg_get(cfg, "command", "")
        url = _cfg_get(cfg, "url", "")
        headers = _cfg_get(cfg, "headers", {}) or {}

        if not transport:
            transport = "stdio" if command else "streamable-http"

        if transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            return stdio_client(
                StdioServerParameters(
                    command=command,
                    args=_cfg_get(cfg, "args", []),
                    env=_cfg_get(cfg, "env", {}) or None,
                )
            )

        if transport == "sse":
            from mcp.client.sse import sse_client

            return sse_client(url)

        if transport in {"streamable-http", "streamable_http", "http"}:
            try:
                from mcp.client.streamable_http import streamable_http_client as _streamable_client
            except ImportError:
                from mcp.client.streamable_http import streamablehttp_client as _streamable_client

            if not headers:
                return _streamable_client(url)

            @asynccontextmanager
            async def _with_headers():
                async with httpx.AsyncClient(
                    headers=headers,
                    follow_redirects=True,
                    timeout=None,
                ) as client:
                    async with _streamable_client(url, http_client=client) as result:
                        yield result

            return _with_headers()

        raise ValueError(f"Unknown MCP transport: {transport}")


async def connect_mcp_servers(mcp_servers: dict, registry: Any, stack: Any) -> None:
    """Backward-compatible connector that registers MCP tools into a registry.

    This keeps compatibility with the upstream loop integration that expects a
    function-based MCP bootstrap using an external AsyncExitStack.
    """
    manager = MCPManager(mcp_servers)
    tools = await manager.start()
    for tool in tools:
        registry.register(tool)

    if hasattr(stack, "push_async_callback"):
        stack.push_async_callback(manager.stop)
