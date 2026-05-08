from __future__ import annotations

WRITE_LIKE_FRAGMENTS = (
    "create",
    "update",
    "delete",
    "remove",
    "assign",
    "claim",
    "transfer",
    "review",
    "audit",
    "sync",
    "send",
    "contact",
    "message",
    "task",
    "export",
    "writeback",
)


def test_v1_tool_names_are_read_only_contract_tools():
    from crm_mcp_server.contract import V1_READ_ONLY_TOOL_NAMES, list_v1_tools

    assert tuple(list_v1_tools()) == V1_READ_ONLY_TOOL_NAMES
    assert V1_READ_ONLY_TOOL_NAMES == (
        "crm_generate_daily_report_facts",
        "crm_generate_weekly_report_facts",
        "crm_generate_dashboard_facts",
        "crm_check_read_boundary",
        "crm_smoke_check",
        "crm_list_projects",
    )


def test_no_write_like_tool_names_are_exposed():
    from crm_mcp_server.contract import list_v1_tools

    exposed_tools = tuple(list_v1_tools())

    assert exposed_tools
    for tool_name in exposed_tools:
        for fragment in WRITE_LIKE_FRAGMENTS:
            assert fragment not in tool_name


def test_server_metadata_lists_only_read_only_tools():
    from crm_mcp_server.server import get_server_metadata

    metadata = get_server_metadata()

    assert metadata["real_crm_access_enabled"] is False
    assert metadata["tools"]
    for tool in metadata["tools"]:
        assert tool["read_only"] is True
        assert tool["name"].startswith("crm_")
        for fragment in WRITE_LIKE_FRAGMENTS:
            assert fragment not in tool["name"]
