"""Adapter to convert MCP tools to nanobot Tool interface."""

import asyncio
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.mcp.client import MCPClient
from nanobot.mcp.security import (
    sanitize_tool_name,
    validate_command,
    validate_script_path,
    validate_sse_url,
)


class MCPToolAdapter(Tool):
    """
    Adapter that wraps an MCP tool as a nanobot Tool.
    
    This allows MCP tools to be used seamlessly with nanobot's tool system.
    
    Example:
        client = MCPClient()
        await client.connect_stdio("filesystem", "python", ["fs.py"])
        
        # Create adapter for each MCP tool
        for tool_def in client.get_all_tools():
            tool = MCPToolAdapter(client, tool_def["full_name"], tool_def)
            registry.register(tool)
    """
    
    def __init__(
        self, 
        client: MCPClient, 
        full_name: str, 
        tool_def: dict[str, Any]
    ):
        self._client = client
        self._full_name = full_name
        self._tool_def = tool_def
    
    @property
    def name(self) -> str:
        """Return the tool name with mcp_ prefix to avoid collisions."""
        sanitized = sanitize_tool_name(self._full_name)
        return f"mcp_{sanitized}"
    
    @property
    def description(self) -> str:
        """Return the tool description."""
        return self._tool_def.get("description", f"MCP tool: {self._full_name}")
    
    @property
    def parameters(self) -> dict[str, Any]:
        """Return the tool parameters in OpenAI format."""
        schema = self._tool_def.get("input_schema", {})
        
        params = {
            "type": "object",
            "properties": schema.get("properties", {}),
        }
        
        if "required" in schema:
            params["required"] = schema["required"]
        
        return params
    
    async def execute(self, **kwargs: Any) -> str:
        """Execute the MCP tool."""
        try:
            return await self._client.call_tool(self._full_name, kwargs)
        except Exception as e:
            return f"Error executing MCP tool {self._full_name}: {str(e)}"


class MCPManager:
    """
    Manager for MCP connections and tools.
    
    Handles multiple MCP servers via stdio or SSE transports.
    
    Config format supports both transport types:
    
    # Stdio example:
    {
        "command": "python",
        "args": ["/path/to/server.py"],
        "env": {"KEY": "value"}
    }
    
    # SSE example:
    {
        "transport": "sse",
        "url": "https://mcp.example.com/server",
        "headers": {"Authorization": "Bearer token"}
    }
    
    Example:
        manager = MCPManager()
        await manager.initialize({
            "local_calc": {
                "command": "python",
                "args": ["calc.py"]
            },
            "remote_db": {
                "transport": "sse",
                "url": "https://mcp.example.com/postgres"
            }
        })
    """
    
    def __init__(self):
        self._client = MCPClient()
        self._tools: list[MCPToolAdapter] = []
        self._initialized = False
    
    async def initialize(self, servers_config: dict[str, dict[str, Any]]) -> None:
        """
        Initialize connections to all configured MCP servers.
        
        Args:
            servers_config: Dict of server_name -> config
                Auto-detects transport type based on config keys.
        """
        if self._initialized:
            return
        
        for server_name, config in servers_config.items():
            try:
                # Use timeout to prevent hanging on slow/unresponsive servers
                transport_type = config.get("transport", "stdio")
                timeout_seconds = 30.0 if transport_type == "sse" else 10.0
                
                if transport_type == "sse":
                    await asyncio.wait_for(
                        self._connect_sse(server_name, config),
                        timeout=timeout_seconds
                    )
                else:
                    await asyncio.wait_for(
                        self._connect_stdio(server_name, config),
                        timeout=timeout_seconds
                    )
                    
            except asyncio.TimeoutError:
                logger.error(f"Timeout connecting to MCP server '{server_name}' after {timeout_seconds}s")
            except Exception as e:
                logger.error(f"Failed to initialize MCP server '{server_name}': {e}")
                # Continue with other servers
        
        # Create tool adapters for all discovered tools
        for tool_def in self._client.get_all_tools():
            adapter = MCPToolAdapter(self._client, tool_def["full_name"], tool_def)
            self._tools.append(adapter)
        
        self._initialized = True
        logger.info(f"MCP Manager initialized with {len(self._tools)} tools")
    
    async def _connect_stdio(self, name: str, config: dict[str, Any]) -> None:
        """Connect to a local MCP server via stdio with security validation."""
        command = config.get("command", "python")
        args = config.get("args", [])
        env = config.get("env")
        
        if not args:
            logger.warning(f"MCP server '{name}' has no args, skipping")
            return
        
        script_path = args[0]
        
        # Validate command against whitelist
        is_valid, error_msg = validate_command(command, args)
        if not is_valid:
            logger.error(f"MCP server '{name}' security validation failed: {error_msg}")
            return
        
        # Validate script path
        is_valid, error_msg = validate_script_path(script_path)
        if not is_valid:
            logger.error(f"MCP server '{name}' path validation failed: {error_msg}")
            return
        
        # Check file exists
        from pathlib import Path
        if not Path(script_path).exists():
            logger.warning(f"MCP server '{name}' script not found: {script_path}")
            return
        
        await self._client.connect_stdio(name, command, args, env)
    
    async def _connect_sse(self, name: str, config: dict[str, Any]) -> None:
        """Connect to a remote MCP server via SSE with security validation."""
        url = config.get("url")
        headers = config.get("headers")
        
        if not url:
            logger.warning(f"MCP server '{name}' has no URL, skipping")
            return
        
        # Validate URL to prevent SSRF
        is_valid, error_msg = validate_sse_url(url)
        if not is_valid:
            logger.error(f"MCP server '{name}' URL validation failed: {error_msg}")
            return
        
        await self._client.connect_sse(name, url, headers)
    
    def get_tools(self) -> list[MCPToolAdapter]:
        """Get all MCP tool adapters."""
        return self._tools
    
    def get_tool(self, name: str) -> MCPToolAdapter | None:
        """Get a specific tool by its nanobot name (with mcp_ prefix)."""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None
    
    async def close(self) -> None:
        """Close all MCP connections."""
        await self._client.close()
        self._tools.clear()
        self._initialized = False
