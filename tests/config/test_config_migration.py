import json
import socket
from unittest.mock import patch

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.security.network import validate_url_target


def _fake_resolve(host: str, results: list[str]):
    """Return a getaddrinfo mock that maps the given host to fake IP results."""
    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in results]
        raise socket.gaierror(f"cannot resolve {hostname}")
    return _resolver


def test_load_config_keeps_max_tokens_and_ignores_legacy_memory_window(tmp_path) -> None:
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

    assert config.resolve_default_preset().max_tokens == 1234
    assert config.resolve_default_preset().context_window_tokens == 200_000
    assert not hasattr(config.agents.defaults, "memory_window")


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
    default_preset = saved["modelPresets"]["default"]

    assert default_preset["maxTokens"] == 2222
    assert default_preset["contextWindowTokens"] == 200_000
    assert "maxTokens" not in defaults
    assert "contextWindowTokens" not in defaults
    assert "memoryWindow" not in defaults


def test_onboard_does_not_crash_with_legacy_memory_window(tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr("nanobot.cli.commands.get_workspace_path", lambda _workspace=None: workspace)

    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    runner = CliRunner()
    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0


@pytest.mark.parametrize("field_name", ["maxMessages", "max_messages"])
def test_load_config_ignores_legacy_max_messages(tmp_path, field_name) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {field_name: 25, "maxTokens": 1234}}}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.resolve_default_preset().max_tokens == 1234
    assert not hasattr(config.agents.defaults, "max_messages")


def test_save_config_drops_legacy_max_messages(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"maxMessages": 25}}}),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert "maxMessages" not in saved["agents"]["defaults"]
    assert "max_messages" not in saved["agents"]["defaults"]


def test_load_config_rewrites_legacy_model_fields_to_default_preset(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "agents": {
                "defaults": {
                    "model": "openai/gpt-4.1",
                    "provider": "openai",
                    "temperature": 0,
                }
            }
        }),
        encoding="utf-8",
    )

    config = load_config(config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert config.agents.defaults.model_preset == "default"
    assert config.resolve_default_preset().model == "openai/gpt-4.1"
    assert saved["agents"]["defaults"]["modelPreset"] == "default"
    assert "model" not in saved["agents"]["defaults"]
    assert saved["modelPresets"]["default"]["model"] == "openai/gpt-4.1"
    assert saved["modelPresets"]["default"]["temperature"] == 0


def test_load_config_prefers_existing_default_preset_over_legacy_fields(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "modelPresets": {
                "default": {
                    "model": "anthropic/claude-opus-4-5",
                    "provider": "anthropic",
                    "maxTokens": 8192,
                }
            },
            "agents": {
                "defaults": {
                    "model": "openai/gpt-4.1",
                    "provider": "openai",
                    "maxTokens": 4096,
                }
            },
        }),
        encoding="utf-8",
    )

    config = load_config(config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert config.resolve_default_preset().model == "anthropic/claude-opus-4-5"
    assert config.resolve_default_preset().provider == "anthropic"
    assert config.resolve_default_preset().max_tokens == 8192
    assert saved["modelPresets"]["default"]["model"] == "anthropic/claude-opus-4-5"
    assert "model" not in saved["agents"]["defaults"]
    assert "provider" not in saved["agents"]["defaults"]
    assert "maxTokens" not in saved["agents"]["defaults"]


def test_load_config_does_not_migrate_legacy_model_fields_from_environment(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "NANOBOT_AGENTS",
        json.dumps({
            "defaults": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
                "maxTokens": 4096,
            }
        }),
    )

    config = load_config(tmp_path / "missing-config.json")

    assert config.resolve_default_preset().model == "anthropic/claude-opus-4-5"
    assert config.resolve_default_preset().provider == "auto"
    assert config.resolve_default_preset().max_tokens == 8192


def test_load_config_migrates_inline_fallback_to_named_preset(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "agents": {
                "defaults": {
                    "model": "openai/gpt-4.1",
                    "provider": "openai",
                    "fallbackModels": [{
                        "model": "anthropic/claude-sonnet-4",
                        "provider": "anthropic",
                    }],
                }
            }
        }),
        encoding="utf-8",
    )

    config = load_config(config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert config.agents.defaults.fallback_models == ["claude-sonnet-4"]
    assert saved["agents"]["defaults"]["fallbackModels"] == ["claude-sonnet-4"]
    assert saved["modelPresets"]["claude-sonnet-4"]["provider"] == "anthropic"


def test_onboard_refresh_backfills_missing_channel_fields(tmp_path, monkeypatch) -> None:
    from nanobot.channels.plugin import load_channel_package

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
    monkeypatch.setattr("nanobot.cli.commands.get_workspace_path", lambda _workspace=None: workspace)
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda: {"qq": load_channel_package("qq")},
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: pytest.fail("onboarding must not import channel runtimes"),
    )

    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    runner = CliRunner()
    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["channels"]["qq"]["msgFormat"] == "plain"


def test_load_config_migrates_legacy_my_tool_keys(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.my.enable is False
    assert config.tools.my.allow_set is True


def test_save_config_rewrites_legacy_my_tool_keys(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    tools = saved["tools"]
    assert "myEnabled" not in tools
    assert "mySet" not in tools
    assert tools["my"] == {"enable": False, "allowSet": True}


def test_new_my_tool_keys_take_precedence_over_legacy(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": False,
                    "my": {"enable": True, "allowSet": True},
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.my.enable is True
    assert config.tools.my.allow_set is True


def test_load_config_resets_ssrf_whitelist_when_next_config_is_empty(tmp_path) -> None:
    whitelisted = tmp_path / "whitelisted.json"
    whitelisted.write_text(
        json.dumps({"tools": {"ssrfWhitelist": ["100.64.0.0/10"]}}),
        encoding="utf-8",
    )
    defaulted = tmp_path / "defaulted.json"
    defaulted.write_text(json.dumps({}), encoding="utf-8")

    load_config(whitelisted)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
        ok, err = validate_url_target("http://ts.local/api")
        assert ok, err

    load_config(defaulted)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
        ok, _ = validate_url_target("http://ts.local/api")
        assert not ok


def test_load_config_defaults_local_service_access_to_enabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": {}}), encoding="utf-8")

    config = load_config(config_path)

    assert config.tools.webui_allow_local_service_access is True


def test_load_config_accepts_legacy_local_preview_access(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"allowLocalPreviewAccess": False}}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.webui_allow_local_service_access is False


def test_load_config_defaults_remote_package_install_to_disabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": {}}), encoding="utf-8")

    config = load_config(config_path)

    assert config.tools.webui_allow_remote_package_install is False


def test_load_config_accepts_remote_package_install_aliases(tmp_path) -> None:
    camel_path = tmp_path / "camel.json"
    camel_path.write_text(
        json.dumps({"tools": {"webuiAllowRemotePackageInstall": True}}),
        encoding="utf-8",
    )
    snake_path = tmp_path / "snake.json"
    snake_path.write_text(
        json.dumps({"tools": {"webui_allow_remote_package_install": True}}),
        encoding="utf-8",
    )

    assert load_config(camel_path).tools.webui_allow_remote_package_install is True
    assert load_config(snake_path).tools.webui_allow_remote_package_install is True


def test_load_config_does_not_rewrite_unrelated_partial_config(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    raw = '{"channels":{"telegram":{"enabled":false}}}'
    config_path.write_text(raw, encoding="utf-8")

    config = load_config(config_path)

    assert config.resolve_default_preset().model == "anthropic/claude-opus-4-5"
    assert config_path.read_text(encoding="utf-8") == raw
