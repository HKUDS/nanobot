from __future__ import annotations

import importlib
import socket
from pathlib import Path


def test_package_imports_without_runtime_config(monkeypatch):
    forbidden_env = [
        "CRM_GRAPHQL_ENDPOINT",
        "CRM_GRAPHQL_TOKEN",
        "NANOBOT_CRM_GRAPHQL_ENDPOINT",
        "NANOBOT_CRM_GRAPHQL_TOKEN",
    ]
    for name in forbidden_env:
        monkeypatch.delenv(name, raising=False)

    package = importlib.import_module("crm_mcp_server")
    server = importlib.import_module("crm_mcp_server.server")

    assert package.__version__
    assert server.get_server_metadata()["name"] == "crm-mcp-server"


def test_skeleton_start_does_not_require_env_file_or_network(monkeypatch):
    opened_paths: list[str] = []
    connected_addresses: list[object] = []

    original_open = Path.open

    def tracking_open(self: Path, *args, **kwargs):
        opened_paths.append(str(self))
        if self.name == ".env.nanobot":
            raise AssertionError("skeleton must not read .env.nanobot")
        return original_open(self, *args, **kwargs)

    def fake_connect(self: socket.socket, address):
        connected_addresses.append(address)
        raise AssertionError("skeleton must not open network connections")

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(socket.socket, "connect", fake_connect)

    from crm_mcp_server.server import create_server_skeleton

    skeleton = create_server_skeleton()

    assert skeleton.metadata.name == "crm-mcp-server"
    assert skeleton.runtime.real_crm_access_enabled is False
    assert not connected_addresses
    assert not any(path.endswith(".env.nanobot") for path in opened_paths)


def test_runtime_defaults_disable_real_crm_access():
    from crm_mcp_server.server import create_server_skeleton

    skeleton = create_server_skeleton()

    runtime = skeleton.runtime

    assert runtime.real_crm_access_enabled is False
    assert runtime.requires_endpoint is False
    assert runtime.requires_token is False
    assert runtime.network_enabled is False


def test_report_assistant_tools_are_exposed_with_write_flag():
    from crm_mcp_server.server import get_server_metadata
    from crm_mcp_server.tool_runtime import list_tool_definitions

    expected_tools = {
        "crm_collect_sales_daily_context": True,
        "crm_collect_sales_weekly_context": True,
        "crm_collect_presales_weekly_context": True,
        "crm_generate_sales_daily_draft": True,
        "crm_generate_sales_weekly_draft": True,
        "crm_generate_presales_weekly_table": True,
        "crm_create_report_after_confirmation": False,
    }

    metadata = {tool["name"]: tool for tool in get_server_metadata()["tools"]}
    assert set(metadata) == {tool.name for tool in list_tool_definitions()}
    assert set(metadata) == set(expected_tools)
    for tool_name, read_only in expected_tools.items():
        assert metadata[tool_name]["read_only"] is read_only


def test_server_metadata_excludes_legacy_tools_for_stdio_phase():
    from crm_mcp_server.server import get_server_metadata

    metadata_tool_names = {tool["name"] for tool in get_server_metadata()["tools"]}

    assert metadata_tool_names.isdisjoint(
        {
            "crm_smoke_check",
            "crm_list_projects",
            "crm_list_business_chances",
            "crm_generate_daily_report_facts",
            "crm_generate_weekly_report_facts",
            "crm_generate_dashboard_facts",
            "crm_check_read_boundary",
        }
    )


def test_report_assistant_query_allow_list_includes_verified_sources():
    from crm_mcp_server.contract import list_v1_query_names

    assert {
        "listReport",
        "reportInfo",
        "reportRelatedInfo",
        "listProject",
        "listProjectID",
        "listActivity",
        "list_leads",
        "list_leads_pool",
        "list_opportunity_scenario",
        "listImmediatelySignProject",
    } <= set(list_v1_query_names())
