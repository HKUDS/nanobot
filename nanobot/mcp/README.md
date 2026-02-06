# MCP (Model Context Protocol) Support for nanobot

This module adds MCP client support to nanobot, enabling integration with the growing ecosystem of MCP servers.

## What is MCP?

MCP (Model Context Protocol) is an open protocol that standardizes how AI assistants connect to external data sources and tools. It was created by Anthropic and donated to the Linux Foundation in December 2025.

Learn more at: https://modelcontextprotocol.io

## Installation

MCP support is available as an optional dependency:

```bash
pip install nanobot-ai[mcp]
```

Or install MCP directly:

```bash
pip install mcp>=1.20.0
```

## Quick Start

### 1. Enable MCP in your config

Edit `~/.nanobot/config.json`:

```json
{
  "tools": {
    "mcp": {
      "enabled": true,
      "servers": {
        "calculator": {
          "command": "python",
          "args": ["~/.nanobot/mcp/servers/calculator.py"]
        }
      }
    }
  }
}
```

### 2. Create an MCP server

Save this as `~/.nanobot/mcp/servers/calculator.py`:

```python
#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calculator")

@mcp.tool()
def add(a: float, b: float) -> str:
    """Add two numbers."""
    return f"{a} + {b} = {a + b}"

if __name__ == "__main__":
    mcp.run()
```

### 3. Run nanobot

```bash
nanobot agent -m "What is 10 + 20?"
```

The agent will automatically use the MCP calculator tool!

## Configuration Reference

```json
{
  "tools": {
    "mcp": {
      "enabled": true,
      "servers": {
        "server-name": {
          "command": "python",
          "args": ["/path/to/server.py"],
          "env": {
            "OPTIONAL_VAR": "value"
          }
        }
      }
    }
  }
}
```

## Finding MCP Servers

- **Official MCP Servers**: https://github.com/modelcontextprotocol/servers
- **Community Servers**: Search "mcp-server" on npm or PyPI

## Architecture

```
nanobot
├── MCPClient          # Manages connections to MCP servers
├── MCPToolAdapter     # Adapts MCP tools to nanobot Tool interface
└── MCPManager         # Handles multiple servers and tool registration
```

## Example Servers

See `examples/mcp/servers/` for example MCP servers:

- `calculator.py` - Mathematical operations
- `datetime.py` - Date and time utilities
- `system.py` - System information

## Troubleshooting

### MCP not available

```
WARNING: MCP support not available. Install with: pip install nanobot-ai[mcp]
```

Solution: Install the MCP dependency

### Server connection failed

Check the logs with verbose mode:

```bash
nanobot gateway --verbose
```

### Permission denied

Make server scripts executable:

```bash
chmod +x ~/.nanobot/mcp/servers/*.py
```
