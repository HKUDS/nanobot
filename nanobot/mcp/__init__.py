"""MCP (Model Context Protocol) client integration for nanobot.

This module enables nanobot to connect to MCP servers and use their tools.
MCP is an open protocol for connecting AI assistants to external data sources and tools.

Example:
    from nanobot.mcp import MCPClient
    
    client = MCPClient()
    await client.connect_to_server("filesystem", "/path/to/server.py")
    tools = await client.get_all_tools()
"""

try:
    from nanobot.mcp.client import MCPClient
    from nanobot.mcp.tool_adapter import MCPToolAdapter
    __all__ = ["MCPClient", "MCPToolAdapter"]
except ImportError as e:
    # MCP not installed
    import warnings
    warnings.warn(
        "MCP support not available. Install with: pip install nanobot-ai[mcp]",
        ImportWarning,
        stacklevel=2
    )
    MCPClient = None  # type: ignore
    MCPToolAdapter = None  # type: ignore
    __all__ = []
