"""CRM MCP server skeleton with no real CRM access."""

from __future__ import annotations

from crm_mcp_server.contract import list_v1_tools
from crm_mcp_server.schemas import RuntimeMetadata, ServerMetadata, ServerSkeleton, ToolMetadata

SERVER_NAME = "crm-mcp-server"
SERVER_VERSION = "0.1.0"
SERVER_DESCRIPTION = "Read-only CRM MCP server skeleton"

_TOOL_DESCRIPTIONS = {
    "crm_generate_daily_report_facts": "Return sanitized daily report facts.",
    "crm_generate_weekly_report_facts": "Return sanitized weekly report facts.",
    "crm_generate_dashboard_facts": "Return sanitized dashboard facts.",
    "crm_check_read_boundary": "Report read-only boundary status without secrets.",
    "crm_smoke_check": "Return sanitized CRM read-boundary diagnostics using mocked transport.",
    "crm_list_projects": "Return sanitized project records from mocked listProject responses.",
}


def create_server_skeleton() -> ServerSkeleton:
    """Create static server skeleton metadata without config, env files, or network access."""

    tools = tuple(
        ToolMetadata(
            name=name,
            read_only=True,
            description=_TOOL_DESCRIPTIONS[name],
        )
        for name in list_v1_tools()
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
