from __future__ import annotations

import json


def test_module_main_metadata_mode_prints_safe_tool_names(capsys):
    from crm_mcp_server.__main__ import main

    exit_code = main(["--metadata"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["name"] == "crm-mcp-server"
    assert "crm_collect_sales_daily_context" in result["tools"]
    assert "crm_create_report_after_confirmation" in result["tools"]
    assert "CRM_GRAPHQL_TOKEN" not in captured.out
    assert "Authorization" not in captured.out


def test_module_main_metadata_tools_match_stdio_preflight(capsys):
    from crm_mcp_server.__main__ import main
    from crm_mcp_server.stdio_server import mcp_tool_payloads

    exit_code = main(["--metadata"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert set(result["tools"]) == {payload["name"] for payload in mcp_tool_payloads()}


def test_module_main_without_metadata_starts_stdio_server(monkeypatch):
    from crm_mcp_server import __main__

    calls: list[str] = []

    def fake_run_stdio_server() -> None:
        calls.append("started")

    monkeypatch.setattr(__main__, "run_stdio_server", fake_run_stdio_server)

    assert __main__.main([]) == 0
    assert calls == ["started"]
