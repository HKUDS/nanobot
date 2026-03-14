import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from nanobot.config.schema import Config
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
    monkeypatch.setattr("nanobot.cli.commands.get_workspace_path", lambda: workspace)

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
    monkeypatch.setattr("nanobot.cli.commands.get_workspace_path", lambda: workspace)
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


def test_load_config_accepts_gateway_ok_signal_fields(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "gateway": {
                    "heartbeat": {
                        "okSignal": "HB_DONE",
                        "sendOkSignalMessages": False,
                    },
                    "cron": {
                        "okSignal": "CRON_DONE",
                        "sendOkSignalMessages": False,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.gateway.heartbeat.ok_signal == "HB_DONE"
    assert config.gateway.heartbeat.send_ok_signal_messages is False
    assert config.gateway.cron.ok_signal == "CRON_DONE"
    assert config.gateway.cron.send_ok_signal_messages is False


@pytest.mark.parametrize("path", ["heartbeat", "cron"])
def test_gateway_ok_signal_rejects_empty_values(path: str) -> None:
    with pytest.raises(ValueError, match="ok_signal must not be empty"):
        Config.model_validate({
            "gateway": {
                path: {
                    "okSignal": "   ",
                }
            }
        })
