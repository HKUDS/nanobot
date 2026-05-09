from __future__ import annotations

from pathlib import Path

import yaml

from nanobot.config.schema import Config

EXAMPLE_PATH = Path("docs/crm/examples/nanobot-crm-mcp.mock.yaml")

EXPECTED_ENABLED_TOOLS = [
    "crm_collect_sales_daily_context",
    "crm_collect_sales_weekly_context",
    "crm_collect_presales_weekly_context",
    "crm_generate_sales_daily_draft",
    "crm_generate_sales_weekly_draft",
    "crm_generate_presales_weekly_table",
    "crm_create_report_after_confirmation",
]

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
SENSITIVE_MARKERS = (
    "CRM_GRAPHQL_TOKEN",
    "NANOBOT_API_KEY",
    "Authorization",
    "Bearer",
    ".env",
    "api.in.chaitin.net",
    "crm/query",
)


def _read_example() -> dict[str, object]:
    return yaml.safe_load(EXAMPLE_PATH.read_text())


def test_crm_mcp_mock_example_uses_expected_tools_only() -> None:
    config = _read_example()
    server = config["tools"]["mcpServers"]["crm"]

    assert server["enabledTools"] == EXPECTED_ENABLED_TOOLS
    for tool_name in server["enabledTools"]:
        if tool_name == "crm_create_report_after_confirmation":
            continue
        for fragment in WRITE_LIKE_FRAGMENTS:
            assert fragment not in tool_name


def test_crm_mcp_mock_example_contains_no_secret_or_real_endpoint_markers() -> None:
    text = EXAMPLE_PATH.read_text()

    for marker in SENSITIVE_MARKERS:
        assert marker not in text


def test_crm_mcp_mock_example_matches_nanobot_config_schema() -> None:
    data = _read_example()

    config = Config.model_validate(data)
    crm_server = config.tools.mcp_servers["crm"]

    assert crm_server.type == "stdio"
    assert crm_server.command == "uv"
    assert crm_server.args == [
        "run",
        "--project",
        "crm_mcp_server",
        "python",
        "-m",
        "crm_mcp_server",
    ]
    assert crm_server.enabled_tools == EXPECTED_ENABLED_TOOLS
    assert crm_server.tool_timeout == 30
    assert crm_server.env == {}
    assert crm_server.headers == {}
