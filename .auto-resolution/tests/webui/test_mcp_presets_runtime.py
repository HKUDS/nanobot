from __future__ import annotations

from types import SimpleNamespace

from nanobot.webui import mcp_presets_runtime


def test_mcp_preset_runtime_lines_describe_tool_prefix() -> None:
    msg = SimpleNamespace(
        content="use @browserbase",
        metadata={
            "mcp_presets": [{
                "name": "browserbase",
                "display_name": "Browserbase",
                "transport": "streamableHttp",
            }],
        },
    )

    lines = mcp_presets_runtime.runtime_lines(
        msg,
        configured_server_names={"browserbase"},
        connected_server_names={"browserbase"},
    )

    assert lines
    assert "@browserbase" in lines[0]
    assert "mcp_browserbase_" in lines[0]
    assert "shell commands" in lines[0]


def test_mcp_preset_runtime_lines_warn_when_restart_needed() -> None:
    msg = SimpleNamespace(
        content="use @browserbase",
        metadata={
            "mcp_presets": [{
                "name": "browserbase",
                "display_name": "Browserbase",
                "transport": "streamableHttp",
            }],
        },
    )

    lines = mcp_presets_runtime.runtime_lines(
        msg,
        configured_server_names=set(),
        connected_server_names=set(),
    )

    assert lines
    assert "has not loaded the latest MCP settings" in lines[0]


def test_mcp_preset_runtime_lines_warn_when_connection_not_live() -> None:
    msg = SimpleNamespace(
        content="use @browserbase",
        metadata={
            "mcp_presets": [{
                "name": "browserbase",
                "display_name": "Browserbase",
                "transport": "streamableHttp",
            }],
        },
    )

    lines = mcp_presets_runtime.runtime_lines(
        msg,
        configured_server_names={"browserbase"},
        connected_server_names=set(),
    )

    assert lines
    assert "connection is not currently live" in lines[0]


def test_mcp_preset_session_extra_only_persists_structured_mentions() -> None:
    assert mcp_presets_runtime.session_extra({}) == {}
    assert mcp_presets_runtime.session_extra({
        "mcp_presets": [{"name": "browserbase"}],
    }) == {"mcp_presets": [{"name": "browserbase"}]}
