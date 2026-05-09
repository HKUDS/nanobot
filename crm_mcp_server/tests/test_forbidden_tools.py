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


def test_v1_tool_names_are_live_stdio_contract_tools():
    from crm_mcp_server.contract import V1_READ_ONLY_TOOL_NAMES, list_v1_read_only_tools

    assert tuple(list_v1_read_only_tools()) == V1_READ_ONLY_TOOL_NAMES
    assert V1_READ_ONLY_TOOL_NAMES == (
        "crm_collect_sales_daily_context",
        "crm_collect_sales_weekly_context",
        "crm_collect_presales_weekly_context",
        "crm_generate_sales_daily_draft",
        "crm_generate_sales_weekly_draft",
        "crm_generate_presales_weekly_table",
    )


def test_v1_tool_names_match_live_stdio_runtime():
    from crm_mcp_server.contract import list_v1_tools
    from crm_mcp_server.tool_runtime import list_tool_definitions

    assert set(list_v1_tools()) == {tool.name for tool in list_tool_definitions()}


def test_no_write_like_tool_names_are_exposed():
    from crm_mcp_server.contract import list_v1_read_only_tools

    exposed_tools = tuple(list_v1_read_only_tools())

    assert exposed_tools
    for tool_name in exposed_tools:
        for fragment in WRITE_LIKE_FRAGMENTS:
            assert fragment not in tool_name


def test_server_metadata_lists_only_read_only_tools():
    from crm_mcp_server.contract import list_v1_write_tools
    from crm_mcp_server.server import get_server_metadata

    metadata = get_server_metadata()
    write_tools = set(list_v1_write_tools())

    assert metadata["real_crm_access_enabled"] is False
    assert metadata["tools"]
    for tool in metadata["tools"]:
        assert tool["name"].startswith("crm_")
        if tool["name"] in write_tools:
            assert tool["read_only"] is False
        else:
            assert tool["read_only"] is True
            for fragment in WRITE_LIKE_FRAGMENTS:
                assert fragment not in tool["name"]
