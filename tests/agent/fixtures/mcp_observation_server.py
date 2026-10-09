"""Local-only MCP fixture: synthetic observations and a lost action response."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
server = Server("observation-fixture")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(name=name, inputSchema={"type": "object", "properties": {}})
        for name in ("observe", "act_then_disconnect")
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    if name == "act_then_disconnect":
        # Persist the side effect, then lose the response. Replaying this call
        # would append a second line, just as a repeated click could submit twice.
        with Path(sys.argv[1]).open("a", encoding="utf-8") as output:
            output.write("action\n")
        os._exit(0)
    return types.CallToolResult(content=[
        types.TextContent(type="text", text="Synthetic window, before image"),
        types.ImageContent(type="image", data=PNG_B64, mimeType="image/png"),
        types.TextContent(type="text", text="After image: target 1"),
    ], structuredContent={"elements": [{"element_token": "s123:1", "label": "AC"}]})


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
