"""CRM MCP server skeleton with no real CRM access."""

from __future__ import annotations

from crm_mcp_server.schemas import RuntimeMetadata, ServerMetadata, ServerSkeleton, ToolMetadata
from crm_mcp_server.tool_runtime import list_tool_definitions

SERVER_NAME = "crm-mcp-server"
SERVER_VERSION = "0.1.0"
SERVER_DESCRIPTION = "CRM MCP server skeleton with read tools and confirmation-gated report write metadata"

_WRITE_TOOL_NAME = "crm_create_report_after_confirmation"


def create_server_skeleton() -> ServerSkeleton:
    """Create static server skeleton metadata without config, env files, or network access."""

    tools = tuple(
        ToolMetadata(
            name=tool.name,
            read_only=tool.name != _WRITE_TOOL_NAME,
            description=tool.description,
        )
        for tool in list_tool_definitions()
    )
    return ServerSkeleton(
        metadata=ServerMetadata(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            description=SERVER_DESCRIPTION,
            tools=tools,
        ),
        runtime=RuntimeMetadata(),
    )


def get_server_metadata() -> dict[str, object]:
    """Return JSON-serializable skeleton metadata for tests and docs checks."""

    skeleton = create_server_skeleton()
    return {
        "name": skeleton.metadata.name,
        "version": skeleton.metadata.version,
        "description": skeleton.metadata.description,
        "real_crm_access_enabled": skeleton.runtime.real_crm_access_enabled,
        "requires_endpoint": skeleton.runtime.requires_endpoint,
        "requires_token": skeleton.runtime.requires_token,
        "network_enabled": skeleton.runtime.network_enabled,
        "tools": [
            {
                "name": tool.name,
                "read_only": tool.read_only,
                "description": tool.description,
            }
            for tool in skeleton.metadata.tools
        ],
    }
