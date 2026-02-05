"""MCP client for connecting to MCP servers via pluggable transports."""

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from loguru import logger
from mcp import ClientSession

from nanobot.mcp.transport import SSETransport, StdioTransport, Transport, TransportError


class MCPServerConnection:
    """Represents a connection to a single MCP server."""
    
    def __init__(self, name: str, session: ClientSession, tools: list[dict[str, Any]]):
        self.name = name
        self.session = session
        self.tools = tools
    
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on this server."""
        try:
            result = await self.session.call_tool(tool_name, arguments)
            
            # Convert result to string
            content_parts = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content_parts.append(item.text)
                elif hasattr(item, 'data'):
                    content_parts.append(str(item.data))
                else:
                    content_parts.append(str(item))
            
            return "\n".join(content_parts) if content_parts else "(no output)"
            
        except Exception as e:
            logger.error(f"Error calling MCP tool {tool_name}: {e}")
            return f"Error: {str(e)}"


class MCPClient:
    """
    Client for connecting to multiple MCP servers via various transports.
    
    Supports both stdio (local processes) and SSE (remote HTTP) transports.
    
    Example:
        client = MCPClient()
        
        # Connect via stdio (local)
        await client.connect_stdio("calc", "python", ["calc.py"])
        
        # Connect via SSE (remote)
        await client.connect_sse("postgres", "https://mcp.example.com/db")
        
        tools = client.get_all_tools()
        result = await client.call_tool("calc:add", {"a": 1, "b": 2})
        
        await client.close()
    """
    
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.connections: dict[str, MCPServerConnection] = {}
        self._transports: dict[str, Transport] = {}
        self._closed = False
    
    async def connect_stdio(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """
        Connect to an MCP server via stdio (local process).
        
        Args:
            name: Unique name for this connection
            command: Command to run (e.g., "python", "node")
            args: Command arguments (first should be script path)
            env: Optional environment variables
        """
        transport = StdioTransport(name=name, command=command, args=args, env=env)
        await self._connect_with_transport(name, transport)
    
    async def connect_sse(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """
        Connect to an MCP server via SSE (HTTP).
        
        Args:
            name: Unique name for this connection
            url: Base URL of the MCP server
            headers: Optional HTTP headers (e.g., Authorization)
        """
        transport = SSETransport(name=name, url=url, headers=headers)
        await self._connect_with_transport(name, transport)
    
    async def _connect_with_transport(self, name: str, transport: Transport) -> None:
        """Internal: connect using a configured transport."""
        if name in self.connections:
            raise ValueError(f"Server '{name}' already connected")
        
        try:
            # Connect transport
            read_stream, write_stream = await transport.connect()
            self._transports[name] = transport
            
            # Wrap in MCP session
            session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            
            # Discover tools
            response = await session.list_tools()
            tools = [
                {"name": tool.name, "description": tool.description, "input_schema": tool.inputSchema}
                for tool in response.tools
            ]
            
            self.connections[name] = MCPServerConnection(name, session, tools)
            logger.info(
                f"MCP server '{name}' connected via {transport.__class__.__name__} "
                f"with {len(tools)} tools"
            )
            
        except Exception as e:
            # Cleanup on failure
            await transport.disconnect()
            raise TransportError(f"Failed to connect to '{name}': {e}") from e
    
    def get_all_tools(self) -> list[dict[str, Any]]:
        """
        Get all tools from all connected servers.
        
        Returns:
            List of tool definitions with server prefix: "server_name:tool_name"
        """
        all_tools = []
        for conn_name, conn in self.connections.items():
            for tool in conn.tools:
                all_tools.append({
                    "server": conn_name,
                    "name": tool["name"],
                    "full_name": f"{conn_name}:{tool['name']}",
                    "description": f"[{conn_name}] {tool['description']}",
                    "input_schema": tool["input_schema"],
                })
        return all_tools
    
    async def call_tool(self, full_name: str, arguments: dict[str, Any]) -> str:
        """
        Call a tool by its full name (server:tool).
        
        Args:
            full_name: Full tool name in format "server:tool_name"
            arguments: Tool arguments
        """
        if ":" not in full_name:
            return f"Error: Invalid tool name '{full_name}'. Expected format: 'server:tool_name'"
        
        server_name, tool_name = full_name.split(":", 1)
        
        if server_name not in self.connections:
            return f"Error: MCP server '{server_name}' not connected"
        
        return await self.connections[server_name].call_tool(tool_name, arguments)
    
    async def close(self) -> None:
        """Close all connections and cleanup."""
        if not self._closed:
            try:
                # Close MCP sessions
                await self.exit_stack.aclose()
            except Exception as e:
                logger.warning(f"Error closing MCP sessions: {e}")
            finally:
                # Always disconnect transports even if exit_stack fails
                for transport in list(self._transports.values()):
                    try:
                        await transport.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting transport: {e}")
                
                self.connections.clear()
                self._transports.clear()
                self._closed = True
                logger.debug("MCP client closed")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
