from __future__ import annotations

import json

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.config.timezone import detect_system_timezone


def test_new_config_detects_backend_timezone(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.config.timezone.get_localzone_name",
        lambda: "Asia/Shanghai",
    )

    config = Config()

    assert config.agents.defaults.timezone == "Asia/Shanghai"
    assert config.agents.defaults.timezone_mode == "auto"


def test_legacy_config_preserves_explicit_timezone(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.config.timezone.get_localzone_name",
        lambda: "Asia/Shanghai",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"timezone": "America/New_York"}}}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents.defaults.timezone == "America/New_York"
    assert config.agents.defaults.timezone_mode == "manual"


def test_auto_timezone_is_detected_by_backend_on_load(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.config.timezone.get_localzone_name",
        lambda: "Asia/Shanghai",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "timezone": "UTC",
                        "timezoneMode": "auto",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents.defaults.timezone == "Asia/Shanghai"
    assert config.agents.defaults.timezone_mode == "auto"


def test_manual_timezone_serializes_explicit_provenance(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {"agents": {"defaults": {"timezone": "America/New_York"}}}
    )

    save_config(config, config_path)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["agents"]["defaults"]["timezone"] == "America/New_York"
    assert saved["agents"]["defaults"]["timezoneMode"] == "manual"


def test_onboard_refresh_materializes_manual_timezone_mode(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"timezone": "America/New_York"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.cli.commands.get_workspace_path",
        lambda _workspace=None: workspace,
    )
    monkeypatch.setattr("nanobot.cli.commands._onboard_plugins", lambda _path: None)

    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    result = CliRunner().invoke(app, ["onboard", "--refresh"])

    assert result.exit_code == 0, result.output
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = saved["agents"]["defaults"]
    assert defaults["timezone"] == "America/New_York"
    assert defaults["timezoneMode"] == "manual"


def test_backend_timezone_detection_falls_back_to_utc(monkeypatch) -> None:
    def unavailable_timezone() -> str:
        raise OSError("timezone unavailable")

    monkeypatch.setattr(
        "nanobot.config.timezone.get_localzone_name",
        unavailable_timezone,
    )

    assert detect_system_timezone() == "UTC"


def test_backend_timezone_detection_normalizes_utc_aliases(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.config.timezone.get_localzone_name",
        lambda: "Etc/UTC",
    )

    assert detect_system_timezone() == "UTC"
