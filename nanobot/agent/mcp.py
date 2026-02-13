"""MCP (Model Context Protocol) integration for nanobot.

Connects to external MCP servers and exposes their tools to the agent.
Supports stdio, SSE, and Streamable HTTP transports.
"""

import json
import os
from contextlib import AsyncExitStack
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import MCPServerConfig


class MCPTool(Tool):
    """Adapter that wraps an MCP tool as a nanobot Tool."""

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        call_fn: Callable[..., Coroutine[Any, Any, str]],
    ):
        self._name = tool_name
        self._description = tool_description
        self._input_schema = input_schema
        self._call_fn = call_fn

    @property
    def name(self) -> str:
        return f"mcp_{self._name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, **kwargs: Any) -> str:
        return await self._call_fn(**kwargs)


class MCPManager:
    """Manages MCP server connections and exposes their tools.

    Usage::

        manager = MCPManager(servers)
        await manager.start()        # connect to all servers
        tools = manager.list_tools()  # get nanobot Tool objects
        await manager.stop()         # disconnect
    """

    def __init__(self, servers: dict[str, MCPServerConfig]):
        self._servers = servers
        self._sessions: dict[str, Any] = {}          # server_name -> ClientSession
        self._tools: dict[str, list[Any]] = {}        # server_name -> MCP tool defs
        self._exit_stack = AsyncExitStack()

    async def start(self) -> None:
        """Connect to all configured MCP servers."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        from mcp.client.sse import sse_client
        from mcp.client.streamable_http import streamablehttp_client

        for name, cfg in self._servers.items():
            try:
                cm = self._create_transport(name, cfg, stdio_client, sse_client, streamablehttp_client)
                if cm is None:
                    continue

                streams = await self._exit_stack.enter_async_context(cm)

                # streamablehttp_client returns (read, write, get_session_id)
                if cfg.transport == "streamable-http":
                    read_stream, write_stream = streams[0], streams[1]
                else:
                    read_stream, write_stream = streams

                session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()

                result = await session.list_tools()
                self._tools[name] = result.tools
                self._sessions[name] = session

                logger.info(f"MCP '{name}': connected, {len(result.tools)} tool(s)")

            except Exception as e:
                logger.error(f"MCP '{name}': failed to connect: {e}")

    def _create_transport(self, name, cfg, stdio_client, sse_client, streamablehttp_client):
        """Create the appropriate transport context manager."""
        if cfg.transport == "stdio":
            if not cfg.command:
                logger.warning(f"MCP '{name}': missing command, skipping")
                return None
            env = {**os.environ, **cfg.env} if cfg.env else None
            return stdio_client(cfg.command, cfg.args, env=env)
        elif cfg.transport == "sse":
            if not cfg.url:
                logger.warning(f"MCP '{name}': missing url, skipping")
                return None
            return sse_client(cfg.url, headers=cfg.headers or None)
        elif cfg.transport == "streamable-http":
            if not cfg.url:
                logger.warning(f"MCP '{name}': missing url, skipping")
                return None
            return streamablehttp_client(cfg.url, headers=cfg.headers or None)
        else:
            logger.warning(f"MCP '{name}': unknown transport '{cfg.transport}'")
            return None

    async def stop(self) -> None:
        """Disconnect all MCP servers."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._tools.clear()

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on a specific MCP server."""
        session = self._sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected"

        try:
            result = await session.call_tool(tool_name, arguments)
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(json.dumps(item.model_dump(), ensure_ascii=False))
            return "\n".join(parts) if parts else "Tool returned no content."
        except Exception as e:
            return f"Error calling MCP tool '{tool_name}': {e}"

    def list_tools(self) -> list[Tool]:
        """Get all MCP tools as nanobot Tool objects."""
        tools: list[Tool] = []
        for server_name, mcp_tools in self._tools.items():
            for t in mcp_tools:

                async def _make_call(
                    _sn: str = server_name,
                    _tn: str = t.name,
                    **kwargs: Any,
                ) -> str:
                    return await self.call_tool(_sn, _tn, kwargs)

                tools.append(MCPTool(
                    tool_name=t.name,
                    tool_description=t.description or "",
                    input_schema=t.inputSchema or {"type": "object", "properties": {}},
                    call_fn=_make_call,
                ))
        return tools
