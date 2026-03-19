import json
from types import SimpleNamespace

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.loader import load_config, save_config

runner = CliRunner()


def test_load_config_keeps_max_tokens_and_warns_on_legacy_memory_window(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 1234,
                        "memoryWindow": 42,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents.defaults.max_tokens == 1234
    assert config.agents.defaults.context_window_tokens == 65_536
    assert config.agents.defaults.should_warn_deprecated_memory_window is True


def test_save_config_writes_context_window_tokens_but_not_memory_window(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 2222,
                        "memoryWindow": 30,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = saved["agents"]["defaults"]

    assert defaults["maxTokens"] == 2222
    assert defaults["contextWindowTokens"] == 65_536
    assert "memoryWindow" not in defaults


def test_onboard_refresh_rewrites_legacy_config_template(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 3333,
                        "memoryWindow": 50,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.cli.commands.get_workspace_path", lambda _workspace=None: workspace
    )

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "contextWindowTokens" in result.stdout
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = saved["agents"]["defaults"]
    assert defaults["maxTokens"] == 3333
    assert defaults["contextWindowTokens"] == 65_536
    assert "memoryWindow" not in defaults


def test_onboard_refresh_backfills_missing_channel_fields(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "qq": {
                        "enabled": False,
                        "appId": "",
                        "secret": "",
                        "allowFrom": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.cli.commands.get_workspace_path", lambda _workspace=None: workspace
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: {
            "qq": SimpleNamespace(
                default_config=lambda: {
                    "enabled": False,
                    "appId": "",
                    "secret": "",
                    "allowFrom": [],
                    "msgFormat": "plain",
                }
            )
        },
    )

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["channels"]["qq"]["msgFormat"] == "plain"


def test_env_ref_round_trip_preserves_placeholder_after_save(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "apiKey": "{env:OPENAI_API_KEY}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-runtime")

    config = load_config(config_path)
    assert config.providers.openai.api_key == "sk-runtime"

    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["openai"]["apiKey"] == "{env:OPENAI_API_KEY}"


def test_env_ref_in_list_round_trip_preserves_placeholder(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "mcpServers": {
                        "demo": {
                            "command": "npx",
                            "args": [
                                "-y",
                                "run-tool",
                                "--token",
                                "{env:MCP_TOKEN}",
                            ],
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_TOKEN", "runtime-token")

    config = load_config(config_path)
    assert config.tools.mcp_servers["demo"].args[3] == "runtime-token"

    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["tools"]["mcpServers"]["demo"]["args"][3] == "{env:MCP_TOKEN}"


def test_save_keeps_intentional_in_memory_override_of_env_ref(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "apiKey": "{env:OPENAI_API_KEY}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    config = load_config(config_path)
    config.providers.openai.api_key = "sk-manual-override"

    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["openai"]["apiKey"] == "sk-manual-override"


def test_missing_env_ref_resolves_empty_at_runtime_but_persists_placeholder(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "apiKey": "{env:MISSING_OPENAI_KEY}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.providers.openai.api_key == ""
    assert config.get_provider_name("openai/gpt-4.1") is None

    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["openai"]["apiKey"] == "{env:MISSING_OPENAI_KEY}"
