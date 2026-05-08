"""Read-only CRM MCP server skeleton."""

from crm_mcp_server.contract import V1_READ_ONLY_TOOL_NAMES, list_v1_tools
from crm_mcp_server.server import create_server_skeleton, get_server_metadata

__all__ = [
    "V1_READ_ONLY_TOOL_NAMES",
    "create_server_skeleton",
    "get_server_metadata",
    "list_v1_tools",
]

__version__ = "0.1.0"
