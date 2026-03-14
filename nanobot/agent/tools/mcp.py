"""MCP client: connects to MCP servers and wraps their tools as native nanobot tools."""

import base64
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """Wraps a single MCP server tool as a nanobot Tool."""

    def __init__(self, session, server_name: str, tool_def):
        self._session = session
        self._server_name = server_name
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = tool_def.description or tool_def.name
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in name)
        return cleaned.strip("-.") or "attachment"

    @staticmethod
    def _image_suffix(mime_type: str | None) -> str:
        if mime_type == "image/jpeg":
            return ".jpg"
        if mime_type == "image/webp":
            return ".webp"
        if mime_type == "image/gif":
            return ".gif"
        return ".png"

    def _save_image_block(self, block: Any, requested_name: str | None = None) -> str:
        output_dir = Path("/tmp/nanobot-mcp") / self._server_name
        output_dir.mkdir(parents=True, exist_ok=True)

        suffix = self._image_suffix(getattr(block, "mimeType", None))
        requested = Path(requested_name).name if requested_name else ""
        filename = self._sanitize_filename(requested) if requested else ""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            filename = f"{self._original_name}-{timestamp}{suffix}"
        elif "." not in filename:
            filename += suffix

        target = output_dir / filename
        target.write_bytes(base64.b64decode(block.data))
        return str(target)

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types
        result = await self._session.call_tool(self._original_name, arguments=kwargs)
        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            elif isinstance(block, types.ImageContent):
                saved_path = self._save_image_block(block, kwargs.get("filename"))
                parts.append(
                    "### Saved Image\n"
                    f"- Local file: {saved_path}\n"
                    "Use the `message` tool with `media=[path]` to send this image to the user."
                )
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """Connect to configured MCP servers and register their tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    for name, cfg in mcp_servers.items():
        try:
            if cfg.command:
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif cfg.url:
                from mcp.client.streamable_http import streamable_http_client
                if cfg.headers:
                    http_client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=cfg.headers,
                            follow_redirects=True
                        )
                    )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(cfg.url, http_client=http_client)
                    )
                else:
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(cfg.url)
                    )
            else:
                logger.warning("MCP server '{}': no command or url configured, skipping", name)
                continue

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools = await session.list_tools()
            for tool_def in tools.tools:
                wrapper = MCPToolWrapper(session, name, tool_def)
                registry.register(wrapper)
                logger.debug("MCP: registered tool '{}' from server '{}'", wrapper.name, name)

            logger.info("MCP server '{}': connected, {} tools registered", name, len(tools.tools))
        except Exception as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)
