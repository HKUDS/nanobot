"""MCP tool integration."""

import asyncio
from typing import Any, List

from langchain_mcp_adapters.client import MultiServerMCPClient

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import MCPToolConfig


class LangChainToolAdapter(Tool):
    """Adapter for LangChain tools to Nanobot tools."""

    def __init__(self, lc_tool: Any):
        self._lc_tool = lc_tool

    @property
    def name(self) -> str:
        return self._lc_tool.name

    @property
    def description(self) -> str:
        return self._lc_tool.description

    @property
    def parameters(self) -> dict[str, Any]:
        # LangChain tools usually expose .args_schema which is a Pydantic model
        # or .args which is a dict schema
        if hasattr(self._lc_tool, "args_schema") and self._lc_tool.args_schema:
            schema = self._lc_tool.args_schema
            if hasattr(schema, "model_json_schema"):
                return schema.model_json_schema()
            if isinstance(schema, dict):
                return schema
                
        # Fallback to manual args construction if needed
        return {
            "type": "object",
            "properties": self._lc_tool.args,
        }

    async def execute(self, **kwargs: Any) -> str:
        try:
            # LangChain tools can be async (ainvoke) or sync (invoke)
            # mcp tools are likely async
            if hasattr(self._lc_tool, "ainvoke"):
                result = await self._lc_tool.ainvoke(kwargs)
            else:
                result = self._lc_tool.invoke(kwargs)
            
            # Parse MCP content format if possible
            if isinstance(result, list):
                texts = []
                for item in result:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(item.get("text", ""))
                if texts:
                    return "\n".join(texts)
            
            return str(result)
        except Exception as e:
            return f"Error executing tool {self.name}: {str(e)}"


class MCPManager:
    """Manages MCP connections and tools."""

    def __init__(self):
        self._client: MultiServerMCPClient | None = None
        self._tools: List[Tool] = []

    async def load_tools(self, configs: dict[str, MCPToolConfig]) -> List[Tool]:
        """Load tools from MCP configurations."""
        connections = {}
        for name, config in configs.items():
            conn = {
                "transport": config.transport,
            }
            if config.command:
                conn["command"] = config.command
            if config.args:
                conn["args"] = config.args
            if config.url:
                conn["url"] = config.url
            if config.env:
                conn["env"] = config.env
            
            connections[name] = conn

        if not connections:
            return []

        try:
            self._client = MultiServerMCPClient(connections)
            lc_tools = await self._client.get_tools()
            
            self._tools = [LangChainToolAdapter(tool) for tool in lc_tools]
            return self._tools
        except Exception as e:
            print(f"Error loading MCP tools: {e}")
            return []

    async def cleanup(self):
        """Close all connections."""
        self._client = None
        self._tools = []
