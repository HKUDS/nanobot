"""MCP tool adapter: wraps an MCP server tool as a nanobot Tool."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from fastmcp import Client as McpClient


class McpToolAdapter(Tool):
    """
    Adapts a single MCP tool into nanobot's Tool interface.

    The tool name is namespaced as ``mcp__{server}__{original_name}`` so it
    cannot collide with built-in tools or tools from other MCP servers.
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        client: McpClient,
    ) -> None:
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = tool_description or f"MCP tool {tool_name} from {server_name}"
        self._input_schema = input_schema or {
            "type": "object",
            "properties": {},
        }
        self._client = client

    # -- Tool interface -------------------------------------------------------

    @property
    def name(self) -> str:
        return f"mcp__{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, **kwargs: Any) -> str:
        """Forward the call to the MCP server via the FastMCP client."""
        try:
            result = await self._client.call_tool(self._tool_name, kwargs)

            # Extract text from the result content blocks
            parts: list[str] = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))

            return "\n".join(parts) if parts else "(empty result)"
        except Exception as e:
            logger.warning(
                f"MCP tool {self.name} execution failed: {e}"
            )
            return f"Error calling MCP tool '{self._tool_name}' on server '{self._server_name}': {e}"
