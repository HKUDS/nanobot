"""MCP (Model Context Protocol) tool adapter and lifecycle manager."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class MCPTool(Tool):
    """Wraps a single MCP server tool as a nanobot Tool."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        session: Any,  # mcp.ClientSession
    ):
        self._server_name = server_name
        self._tool_name = tool_name
        self._tool_description = tool_description
        self._input_schema = input_schema
        self._session = session

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
        try:
            result = await self._session.call_tool(self._tool_name, kwargs)
            parts: list[str] = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            return "\n".join(parts) if parts else "(empty result)"
        except Exception as e:
            return f"MCP Error ({self._server_name}/{self._tool_name}): {e}"


class _ServerHandle:
    """Holds the running state of one MCP server connection.

    Each server runs in its own asyncio Task that keeps the ``async with``
    context managers alive for the lifetime of the connection.
    """

    def __init__(self, name: str):
        self.name = name
        self.task: asyncio.Task[None] | None = None
        self.session: Any = None
        self.tools: list[MCPTool] = []
        self.stop_event = asyncio.Event()


class MCPManager:
    """Manages the lifecycle of MCP server connections."""

    def __init__(self, servers: dict[str, Any]):
        from nanobot.config.schema import McpServerConfig

        self._configs: dict[str, McpServerConfig] = {}
        for name, cfg in servers.items():
            if isinstance(cfg, McpServerConfig):
                if cfg.enabled:
                    self._configs[name] = cfg
            elif isinstance(cfg, dict):
                sc = McpServerConfig(**cfg)
                if sc.enabled:
                    self._configs[name] = sc
            else:
                if getattr(cfg, "enabled", True):
                    self._configs[name] = cfg

        self._handles: list[_ServerHandle] = []

    @property
    def server_names(self) -> list[str]:
        return [h.name for h in self._handles]

    async def start(self) -> list[MCPTool]:
        """Connect to all configured MCP servers, discover tools, return MCPTool list."""
        all_tools: list[MCPTool] = []

        for name, cfg in self._configs.items():
            handle = _ServerHandle(name)
            ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()

            handle.task = asyncio.create_task(
                self._run_server(name, cfg, handle, ready)
            )

            try:
                await ready
                self._handles.append(handle)
                all_tools.extend(handle.tools)
                logger.info(f"MCP server '{name}': {len(handle.tools)} tools discovered")
            except BaseException as e:
                logger.error(f"MCP server '{name}' failed to connect: {e}")
                if handle.task and not handle.task.done():
                    handle.task.cancel()
                    try:
                        await handle.task
                    except (asyncio.CancelledError, BaseException):
                        pass

        return all_tools

    async def stop(self) -> None:
        """Signal all server tasks to stop and wait for them."""
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
        """Run a single MCP server connection in its own task.

        Uses proper ``async with`` to keep transport and session alive.
        Signals *ready* when tools are discovered (or on failure).
        Then waits on ``handle.stop_event`` to keep the connection alive.
        """
        from mcp import ClientSession

        transport_type = cfg.transport

        try:
            cm_transport = self._create_transport(cfg)

            async with cm_transport as transport_result:
                if isinstance(transport_result, tuple):
                    read_stream, write_stream = transport_result[0], transport_result[1]
                else:
                    read_stream, write_stream = transport_result, None

                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    handle.session = session

                    result = await session.list_tools()
                    for t in result.tools:
                        input_schema = (
                            t.inputSchema
                            if hasattr(t, "inputSchema")
                            else {"type": "object", "properties": {}}
                        )
                        handle.tools.append(MCPTool(
                            server_name=name,
                            tool_name=t.name,
                            tool_description=t.description or t.name,
                            input_schema=input_schema,
                            session=session,
                        ))

                    if not ready.done():
                        ready.set_result(None)

                    # Keep connection alive until stop is requested
                    await handle.stop_event.wait()

        except BaseException as e:
            if not ready.done():
                ready.set_exception(e)
            else:
                logger.warning(f"MCP server '{name}' connection lost: {e}")

    @staticmethod
    def _create_transport(cfg: Any) -> Any:
        """Create the appropriate transport context manager."""
        transport = cfg.transport

        if transport == "stdio":
            from mcp.client.stdio import stdio_client, StdioServerParameters
            return stdio_client(StdioServerParameters(
                command=cfg.command,
                args=cfg.args,
                env=cfg.env if cfg.env else None,
            ))
        elif transport == "sse":
            from mcp.client.sse import sse_client
            return sse_client(cfg.url)
        elif transport == "streamable-http":
            from mcp.client.streamable_http import streamablehttp_client
            return streamablehttp_client(cfg.url)
        else:
            raise ValueError(f"Unknown MCP transport: {transport}")
