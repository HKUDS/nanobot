"""MCP adapter for the native host. Transport metadata owns per-turn leases."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from nanobot.apps.computer_use_native import NativeConnection, admin


async def serve(address: Path) -> None:
    server = Server("nanobot-computer-use")
    connections: dict[str, NativeConnection] = {}

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        result = await admin(address, "list")
        return [Tool.model_validate(tool) for tool in result["tools"]]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        meta = server.request_context.meta
        metadata = meta.model_dump() if meta else {}
        scope = metadata.get("nanobot/turn")
        if not isinstance(scope, str) or not scope or len(scope) > 128:
            return CallToolResult(isError=True, content=[TextContent(type="text", text="Computer Use requires a nanobot-owned task context.")])
        if name == "nanobot_finish_turn":
            connection = connections.pop(scope, None)
            if connection is not None:
                await connection.close()
            return CallToolResult(content=[])
        connection = connections.setdefault(scope, NativeConnection(address))
        try:
            result = await connection.request("call", name=name, arguments=arguments)
            return CallToolResult.model_validate(result)
        except asyncio.CancelledError:
            connections.pop(scope, None)
            await connection.close()
            raise
        except Exception as exc:
            connections.pop(scope, None)
            await connection.close()
            return CallToolResult(isError=True, content=[TextContent(type="text", text=str(exc))])

    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await asyncio.gather(*(connection.close() for connection in connections.values()), return_exceptions=True)


if __name__ == "__main__":
    import sys

    asyncio.run(serve(Path(sys.argv[1])))
