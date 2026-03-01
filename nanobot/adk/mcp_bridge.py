"""MCP bridge for ADK: wraps MCP server tools as ADK FunctionTool instances."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from google.adk.tools import FunctionTool
from loguru import logger


async def connect_mcp_servers_adk(
    mcp_servers: dict, stack: AsyncExitStack
) -> list[FunctionTool]:
    """Connect to configured MCP servers and return ADK FunctionTool wrappers."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    all_tools: list[FunctionTool] = []

    for name, cfg in mcp_servers.items():
        try:
            if cfg.command:
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif cfg.url:
                from mcp.client.streamable_http import streamable_http_client

                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,
                        follow_redirects=True,
                        timeout=None,
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )
            else:
                logger.warning("MCP server '{}': no command or url configured, skipping", name)
                continue

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools = await session.list_tools()
            tool_timeout = cfg.tool_timeout

            for tool_def in tools.tools:
                wrapper = _make_mcp_wrapper(session, name, tool_def, tool_timeout)
                ft = FunctionTool(func=wrapper)
                all_tools.append(ft)
                logger.debug("MCP/ADK: registered tool '{}' from server '{}'", tool_def.name, name)

            logger.info(
                "MCP server '{}': connected, {} tools registered (ADK)", name, len(tools.tools)
            )
        except Exception as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)

    return all_tools


def _make_mcp_wrapper(session, server_name: str, tool_def, tool_timeout: int = 30):
    """Create a plain async function wrapping an MCP tool for ADK auto-discovery.

    The function's name becomes `mcp_{server}_{tool}`, and its docstring
    becomes the tool description. ADK discovers parameters from the function
    signature, but MCP tools have dynamic schemas — so we accept **kwargs
    and let ADK pass through the raw arguments.
    """
    original_name = tool_def.name
    func_name = f"mcp_{server_name}_{tool_def.name}"
    description = tool_def.description or tool_def.name

    async def _mcp_call(**kwargs) -> str:
        from mcp import types

        try:
            result = await asyncio.wait_for(
                session.call_tool(original_name, arguments=kwargs),
                timeout=tool_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("MCP tool '{}' timed out after {}s", func_name, tool_timeout)
            return f"(MCP tool call timed out after {tool_timeout}s)"

        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"

    # Set function metadata so ADK can discover name/description
    _mcp_call.__name__ = func_name
    _mcp_call.__qualname__ = func_name
    _mcp_call.__doc__ = description

    return _mcp_call
