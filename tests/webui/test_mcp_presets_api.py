from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path

import pytest
from mcp.shared.auth import OAuthToken

from nanobot.agent.plugins import AGENT_PLUGIN_MCP_SCHEMA, AGENT_PLUGIN_SCHEMA
from nanobot.agent.tools.mcp_oauth import MCPOAuthStorage, mcp_oauth_has_credentials
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.mcp_presets_api import (
    McpPresetError,
    custom_mcp_action,
    mcp_presets_action,
    mcp_presets_payload,
    mcp_presets_settings_action,
    mcp_presets_test_action,
    normalize_mcp_preset_mentions,
)


def _use_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(tmp_path / "workspace")}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)


def _write_agent_plugin(workspace: Path) -> None:
    root = workspace / "plugins" / "desktop"
    root.mkdir(parents=True)
    for filename, payload in (
        (
            "plugin.json",
            {
                "$schema": AGENT_PLUGIN_SCHEMA,
                "name": "desktop",
                "description": "Control the local desktop.",
                "extensions": {
                    "dev.nanobot": {
                        "displayName": "Desktop Control",
                        "permissions": ["screen-recording"],
                    }
                },
            },
        ),
        (
            "mcp.json",
            {
                "$schema": AGENT_PLUGIN_MCP_SCHEMA,
                "mcpServers": {"desktop": {"type": "stdio", "command": "echo"}},
            },
        ),
    ):
        (root / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_mcp_presets_payload_lists_supported_cards(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = mcp_presets_payload()
    names = {preset["name"] for preset in payload["presets"]}

    assert {
        "browserbase",
        "playwright",
        "github",
        "figma",
        "context7",
        "firecrawl",
        "parallel-search",
        "exa",
        "microsoft-learn",
        "aws-docs",
        "brave-search",
        "postman",
        "xmind",
        "notion",
        "linear",
    }.issubset(names)
    browserbase = next(preset for preset in payload["presets"] if preset["name"] == "browserbase")
    assert browserbase["installed"] is False
    assert browserbase["install_supported"] is True
    assert browserbase["required_fields"][0]["configured"] is False
    assert "browserbaseApiKey" not in browserbase["connection_summary"]
    manifest = browserbase["manifest"]
    assert manifest["schema"] == "agent-app.v1"
    assert manifest["id"] == "browserbase"
    assert manifest["source"] == "mcp-preset"
    assert manifest["capabilities"][0]["type"] == "mcp"
    assert manifest["capabilities"][0]["transport"] == "streamableHttp"
    assert manifest["install"]["strategy"] == "config"
    assert manifest["remove"]["verification"] == ["config_absent"]
    assert manifest["trust"]["review_status"] == "builtin_preset"


def test_agent_plugin_reuses_mcp_catalog_and_runtime_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    _write_agent_plugin(load_config().workspace_path)

    row = next(item for item in mcp_presets_payload()["presets"] if item["source"] == "agent-plugin")
    assert (row["name"], row["display_name"], row["requires"]) == (
        "plugin-desktop", "Desktop Control", "screen-recording"
    )
    assert row["installed"] and row["configured"] and not row["enabled"]

    async def reload() -> dict[str, object]:
        return {"ok": True, "message": "MCP reloaded.", "requires_restart": False}

    plugin_action = partial(
        mcp_presets_settings_action,
        query={"name": ["plugin-desktop"]},
    )
    enabled = asyncio.run(plugin_action("enable", reload_mcp=reload))
    enabled_row = next(item for item in enabled["presets"] if item["name"] == "plugin-desktop")
    assert (enabled_row["enabled"], enabled_row["status"], enabled["requires_restart"]) == (
        True, "enabled", False
    )

    disabled = asyncio.run(plugin_action("disable", reload_mcp=reload))
    disabled_row = next(item for item in disabled["presets"] if item["name"] == "plugin-desktop")
    assert (disabled_row["installed"], disabled_row["enabled"], disabled_row["status"]) == (
        True, False, "disabled"
    )

    with pytest.raises(McpPresetError, match="enable and disable"):
        asyncio.run(plugin_action("remove"))

    (load_config().workspace_path / "plugins" / "desktop" / "mcp.json").unlink()
    assert any(item["name"] == "plugin-desktop" for item in mcp_presets_payload()["presets"])

    config_path = tmp_path / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["tools"] = {"mcpServers": {"plugin-desktop": {"type": "stdio", "command": "echo"}}}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rows = [item for item in mcp_presets_payload()["presets"] if item["name"] == "plugin-desktop"]
    assert len(rows) == 1 and rows[0]["source"] == "custom"


@pytest.mark.asyncio
async def test_oauth_preset_is_one_click_configured_after_token_storage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = mcp_presets_action("enable", {"name": ["xmind"]})

    row = next(item for item in payload["presets"] if item["name"] == "xmind")
    assert row["installed"] is True
    assert row["configured"] is False
    assert row["status"] == "authorization_required"
    assert row["transport"] == "streamableHttp"
    assert row["auth"] == "oauth"
    config = load_config()
    cfg = config.tools.mcp_servers["xmind"]
    assert cfg.type == "streamableHttp"
    assert cfg.auth == "oauth"
    assert cfg.url == "https://app.xmind.com/api/mcp"

    await MCPOAuthStorage("xmind", cfg.url).set_tokens(OAuthToken(access_token="secret"))
    connected = mcp_presets_payload()
    row = next(item for item in connected["presets"] if item["name"] == "xmind")
    assert row["configured"] is True
    assert row["status"] == "configured"

    failed = mcp_presets_payload(runtime_status={"xmind": "failed"})
    row = next(item for item in failed["presets"] if item["name"] == "xmind")
    assert row["configured"] is True
    assert row["status"] == "configured"
    assert row["runtime_status"] == "failed"
    assert "secret" not in str(row)

    healthy = mcp_presets_payload(runtime_status={"xmind": "connected"})
    row = next(item for item in healthy["presets"] if item["name"] == "xmind")
    assert row["runtime_status"] == "connected"

    mcp_presets_action("remove", {"name": ["xmind"]})
    assert await MCPOAuthStorage("xmind", cfg.url).get_tokens() is None


@pytest.mark.asyncio
async def test_settings_list_projects_runtime_snapshot_and_reconnects_custom_server(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    custom_mcp_action(
        "custom",
        {
            "name": ["team-docs"],
            "transport": ["streamableHttp"],
            "url": ["https://mcp.example.com/mcp"],
        },
    )
    statuses = {"team-docs": "failed"}
    reload_calls = 0

    async def reload_mcp() -> dict[str, object]:
        nonlocal reload_calls
        reload_calls += 1
        statuses["team-docs"] = "connected"
        return {
            "ok": True,
            "connected": ["team-docs"],
            "failed": [],
            "requires_restart": False,
        }

    listed = await mcp_presets_settings_action(
        None,
        {},
        reload_mcp=reload_mcp,
        mcp_runtime_status=lambda: statuses,
    )
    row = next(item for item in listed["presets"] if item["name"] == "team-docs")
    assert row["configured"] is True
    assert row["runtime_status"] == "failed"
    assert reload_calls == 0

    reconnected = await mcp_presets_settings_action(
        "reconnect",
        {"name": ["team-docs"]},
        reload_mcp=reload_mcp,
        mcp_runtime_status=lambda: statuses,
    )
    row = next(item for item in reconnected["presets"] if item["name"] == "team-docs")
    assert row["runtime_status"] == "connected"
    assert reconnected["requires_restart"] is False
    assert reload_calls == 1


def test_enable_browserbase_writes_scrubbed_config_payload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = mcp_presets_action(
        "enable",
        {
            "name": ["browserbase"],
            "browserbase_api_key": ["bb_live_secret"],
        },
    )

    assert payload["requires_restart"] is True
    assert payload["last_action"]["ok"] is True
    assert payload["last_action"]["installed"] is True
    assert payload["last_action"]["verification"] == ["config_present"]
    preset = next(row for row in payload["presets"] if row["name"] == "browserbase")
    assert preset["installed"] is True
    assert preset["configured"] is True
    assert "bb_live_secret" not in str(payload)
    config = load_config()
    assert "browserbaseApiKey=bb_live_secret" in config.tools.mcp_servers["browserbase"].url


def test_enable_requires_missing_secret(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)

    with pytest.raises(McpPresetError) as exc:
        mcp_presets_action("enable", {"name": ["browserbase"]})

    assert exc.value.status == 400
    assert "Browserbase API key" in exc.value.message


def test_enable_context7_optional_api_key_appends_arg(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = mcp_presets_action(
        "enable",
        {
            "name": ["context7"],
            "context7_api_key": ["ctx7_secret"],
        },
    )

    assert "ctx7_secret" not in str(payload)
    row = next(item for item in payload["presets"] if item["name"] == "context7")
    assert row["configured"] is True
    config = load_config()
    assert config.tools.mcp_servers["context7"].args == [
        "-y",
        "@upstash/context7-mcp@latest",
        "--api-key",
        "ctx7_secret",
    ]


def test_enable_stdio_preset_uses_config_scoped_cwd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    mcp_presets_action("enable", {"name": ["playwright"]})

    config = load_config()
    cwd = config.tools.mcp_servers["playwright"].cwd
    assert cwd == str(tmp_path / "mcp" / "playwright")
    assert (tmp_path / "mcp" / "playwright").is_dir()


def test_enable_no_auth_remote_presets_write_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)

    mcp_presets_action("enable", {"name": ["microsoft-learn"]})
    mcp_presets_action("enable", {"name": ["exa"]})
    mcp_presets_action("enable", {"name": ["firecrawl"]})
    mcp_presets_action("enable", {"name": ["parallel-search"]})

    config = load_config()
    assert config.tools.mcp_servers["microsoft-learn"].url == "https://learn.microsoft.com/api/mcp"
    assert config.tools.mcp_servers["exa"].url == "https://mcp.exa.ai/mcp"
    assert config.tools.mcp_servers["firecrawl"].url == "https://mcp.firecrawl.dev/v2/mcp"
    assert config.tools.mcp_servers["parallel-search"].url == "https://search.parallel.ai/mcp"


def test_firecrawl_preset_is_keyless(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = mcp_presets_action("enable", {"name": ["firecrawl"]})

    row = next(item for item in payload["presets"] if item["name"] == "firecrawl")
    assert row["transport"] == "streamableHttp"
    assert row["requires"] == "Network access"
    assert row["required_fields"] == []
    assert row["configured"] is True
    assert "Keyless" in row["note"]
    config = load_config()
    assert config.tools.mcp_servers["firecrawl"].type == "streamableHttp"
    assert config.tools.mcp_servers["firecrawl"].url == "https://mcp.firecrawl.dev/v2/mcp"
    assert config.tools.mcp_servers["firecrawl"].env == {}


def test_parallel_search_preset_is_keyless_and_tool_limited(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = mcp_presets_action("enable", {"name": ["parallel-search"]})

    row = next(item for item in payload["presets"] if item["name"] == "parallel-search")
    assert row["transport"] == "streamableHttp"
    assert row["requires"] == "Network access"
    assert row["required_fields"] == []
    assert row["configured"] is True
    assert "no API key" in row["note"]
    config = load_config()
    server = config.tools.mcp_servers["parallel-search"]
    assert server.type == "streamableHttp"
    assert server.url == "https://search.parallel.ai/mcp"
    assert server.enabled_tools == ["web_search", "web_fetch"]
    assert server.headers == {}


def test_remove_mcp_preset_updates_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)
    mcp_presets_action("enable", {"name": ["playwright"]})
    managed_cwd = tmp_path / "mcp" / "playwright"
    (managed_cwd / "cache.txt").write_text("managed runtime data", encoding="utf-8")

    payload = mcp_presets_action("remove", {"name": ["playwright"]})

    assert payload["requires_restart"] is True
    assert payload["last_action"]["ok"] is True
    assert payload["last_action"]["removed"] is True
    assert payload["last_action"]["managed_paths_removed"] == ["runtime:mcp/playwright"]
    assert not managed_cwd.exists()
    config = load_config()
    assert "playwright" not in config.tools.mcp_servers


def test_remove_custom_mcp_server_preserves_user_cwd(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)
    user_cwd = tmp_path / "user-cwd"
    user_cwd.mkdir()
    custom_mcp_action(
        "custom",
        {
            "name": ["internal-docs"],
            "transport": ["stdio"],
            "command": ["node"],
            "args": ['["server.js"]'],
            "cwd": [str(user_cwd)],
        },
    )

    payload = mcp_presets_action("remove", {"name": ["internal-docs"]})

    assert payload["last_action"]["ok"] is True
    assert user_cwd.exists()
    config = load_config()
    assert "internal-docs" not in config.tools.mcp_servers


def test_test_mcp_preset_reports_missing_dependency(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    mcp_presets_action("enable", {"name": ["playwright"]})
    monkeypatch.setattr("nanobot.webui.mcp_presets_api.shutil.which", lambda _command: None)

    payload = asyncio.run(mcp_presets_test_action({"name": ["playwright"]}))

    assert payload["last_action"]["ok"] is False
    assert "npx" in payload["last_action"]["message"]


def test_test_mcp_preset_connects_and_reports_tools(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    mcp_presets_action("enable", {"name": ["playwright"]})

    class FakeStack:
        async def aclose(self) -> None:
            return None

    async def fake_connect(servers, registry):
        assert list(servers) == ["playwright"]

        class FakeTool:
            name = "mcp_playwright_browser_navigate"

            def to_schema(self):
                return {"name": self.name, "description": "", "parameters": {}}

        registry.register(FakeTool())
        return {"playwright": FakeStack()}

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", fake_connect)

    payload = asyncio.run(mcp_presets_test_action({"name": ["playwright"]}))

    assert payload["last_action"]["ok"] is True
    assert payload["last_action"]["tool_count"] == 1
    assert payload["last_action"]["tool_names"] == ["mcp_playwright_browser_navigate"]


def test_test_mcp_preset_inspects_tools_outside_the_enabled_allowlist(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    mcp_presets_action("enable", {"name": ["playwright"]})
    config = load_config()
    config.tools.mcp_servers["playwright"].enabled_tools = [
        "mcp_playwright_browser_navigate",
    ]
    save_config(config)

    class FakeStack:
        async def aclose(self) -> None:
            return None

    async def fake_connect(servers, registry):
        assert servers["playwright"].enabled_tools == ["*"]

        class FakeTool:
            def __init__(self, name: str) -> None:
                self.name = name

            def to_schema(self):
                return {"name": self.name, "description": "", "parameters": {}}

        for index in range(20):
            registry.register(FakeTool(f"mcp_playwright_tool_{index:02d}"))
        return {"playwright": FakeStack()}

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", fake_connect)

    payload = asyncio.run(mcp_presets_test_action({"name": ["playwright"]}))

    assert payload["last_action"]["tool_count"] == 20
    assert len(payload["last_action"]["tool_names"]) == 20
    row = next(item for item in payload["presets"] if item["name"] == "playwright")
    assert row["enabled_tools"] == ["mcp_playwright_browser_navigate"]


def test_test_mcp_preset_scrubs_connection_errors(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    mcp_presets_action(
        "enable",
        {
            "name": ["browserbase"],
            "browserbase_api_key": ["bb_live_secret"],
        },
    )

    async def fake_connect(_servers, _registry):
        raise RuntimeError("failed https://mcp.browserbase.com/mcp?browserbaseApiKey=bb_live_secret")

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", fake_connect)

    payload = asyncio.run(mcp_presets_test_action({"name": ["browserbase"]}))

    assert payload["last_action"]["ok"] is False
    assert "bb_live_secret" not in str(payload)
    assert "<redacted>" in payload["last_action"]["error"]


def test_unknown_oauth_placeholder_is_not_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(tmp_path, monkeypatch)

    with pytest.raises(McpPresetError) as exc:
        mcp_presets_action("enable", {"name": ["asana"]})

    assert exc.value.status == 404


def test_normalize_mcp_preset_mentions_keeps_known_presets_only() -> None:
    payload = normalize_mcp_preset_mentions([
        {
            "name": "browserbase",
            "display_name": "Browserbase",
            "transport": "streamableHttp",
            "configured": True,
            "logo_url": "https://example.invalid/logo.svg",
        },
        {"name": "totally-unknown"},
        "bad",
    ])

    assert payload == [{
        "name": "browserbase",
        "display_name": "Browserbase",
        "transport": "streamableHttp",
        "configured": True,
        "logo_url": "https://example.invalid/logo.svg",
    }]


def test_custom_mcp_server_writes_config_and_catalog_row(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = custom_mcp_action(
        "custom",
        {
            "name": ["internal-docs"],
            "transport": ["stdio"],
            "command": ["node"],
            "args": ['["server.js"]'],
            "env": ['{"DOCS_TOKEN":"docs-secret-value"}'],
            "tool_timeout": ["45"],
        },
    )

    assert payload["requires_restart"] is True
    row = next(item for item in payload["presets"] if item["name"] == "internal-docs")
    assert row["source"] == "custom"
    assert row["transport"] == "stdio"
    assert row["connection_summary"] == "node server.js"
    assert row["manifest"]["schema"] == "agent-app.v1"
    assert row["manifest"]["source"] == "mcp-custom"
    assert row["manifest"]["capabilities"][0]["command"] == "node"
    assert "server.js" not in str(row["manifest"])
    assert "docs-secret-value" not in str(payload)
    config = load_config()
    assert config.tools.mcp_servers["internal-docs"].args == ["server.js"]
    assert config.tools.mcp_servers["internal-docs"].env["DOCS_TOKEN"] == "docs-secret-value"


def test_import_mcp_config_and_tool_allowlist(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = custom_mcp_action(
        "import",
        {
            "config": [
                (
                    '{"mcpServers":{'
                    '"docs":{"command":"npx","args":["-y","docs-mcp"],"env":{"API_KEY":"config-secret-value"}},'
                    '"remote-docs":{"transport":"sse","url":"https://example.com/sse"}'
                    '}}'
                )
            ],
        },
    )

    assert payload["last_action"]["message"] == "Imported 2 MCP server(s)."
    config = load_config()
    assert config.tools.mcp_servers["docs"].command == "npx"
    assert config.tools.mcp_servers["docs"].args == ["-y", "docs-mcp"]
    assert config.tools.mcp_servers["remote-docs"].type == "sse"
    assert config.tools.mcp_servers["remote-docs"].url == "https://example.com/sse"
    assert config.tools.mcp_servers["docs"].env["API_KEY"] == "config-secret-value"
    assert "config-secret-value" not in str(payload)

    payload = custom_mcp_action(
        "tools",
        {
            "name": ["docs"],
            "enabled_tools": ['["mcp_docs_search"]'],
        },
    )

    row = next(item for item in payload["presets"] if item["name"] == "docs")
    assert row["enabled_tools"] == ["mcp_docs_search"]
    assert load_config().tools.mcp_servers["docs"].enabled_tools == ["mcp_docs_search"]

    payload = custom_mcp_action(
        "tools",
        {
            "name": ["docs"],
            "enabled_tools": ["[]"],
        },
    )

    row = next(item for item in payload["presets"] if item["name"] == "docs")
    assert row["enabled_tools"] == []
    assert load_config().tools.mcp_servers["docs"].enabled_tools == []


def test_import_recognizes_known_and_explicit_oauth_servers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)

    payload = custom_mcp_action(
        "import",
        {
            "config": [
                (
                    '{"mcpServers":{'
                    '"notion-work":{"url":"https://mcp.notion.com/mcp"},'
                    '"company-mcp":{"url":"https://mcp.example.com/mcp","auth":"oauth"},'
                    '"notion-pat":{"url":"https://mcp.notion.com/mcp",'
                    '"headers":{"Authorization":"Bearer secret"}}'
                    '}}'
                )
            ],
        },
    )

    config = load_config()
    assert config.tools.mcp_servers["notion-work"].auth == "oauth"
    assert config.tools.mcp_servers["company-mcp"].auth == "oauth"
    assert config.tools.mcp_servers["notion-pat"].auth is None
    rows = {row["name"]: row for row in payload["presets"]}
    assert rows["notion-work"]["status"] == "authorization_required"
    assert rows["company-mcp"]["status"] == "authorization_required"
    assert rows["notion-pat"]["status"] == "configured"
    assert "Bearer secret" not in str(payload)


@pytest.mark.asyncio
async def test_replacing_oauth_config_removes_its_stored_credentials(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    custom_mcp_action(
        "custom",
        {
            "name": ["company-mcp"],
            "transport": ["streamableHttp"],
            "url": [server_url],
            "auth": ["oauth"],
        },
    )
    await MCPOAuthStorage("company-mcp", server_url).set_tokens(
        OAuthToken(access_token="secret")
    )
    assert mcp_oauth_has_credentials("company-mcp", server_url)

    custom_mcp_action(
        "custom",
        {
            "name": ["company-mcp"],
            "transport": ["streamableHttp"],
            "url": [server_url],
        },
    )

    assert not mcp_oauth_has_credentials("company-mcp", server_url)


def test_normalize_mcp_preset_mentions_accepts_configured_custom_server(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(tmp_path, monkeypatch)
    custom_mcp_action(
        "custom",
        {
            "name": ["docs"],
            "transport": ["streamableHttp"],
            "url": ["https://example.com/mcp"],
        },
    )

    payload = normalize_mcp_preset_mentions([
        {"name": "docs", "display_name": "Docs", "transport": "streamableHttp"},
    ])

    assert payload == [{"name": "docs", "display_name": "Docs", "transport": "streamableHttp"}]


def test_normalize_mcp_mentions_uses_explicit_gateway_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_path = tmp_path / "default.json"
    config_path = tmp_path / "gateway.json"
    save_config(Config(), default_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", default_path)
    custom_mcp_action(
        "custom",
        {
            "name": ["gateway-docs"],
            "transport": ["streamableHttp"],
            "url": ["https://example.com/mcp"],
        },
        config_path=config_path,
    )

    payload = normalize_mcp_preset_mentions(
        [{"name": "gateway-docs", "display_name": "Gateway docs"}],
        config_path=config_path,
    )

    assert payload == [{"name": "gateway-docs", "display_name": "Gateway docs"}]
