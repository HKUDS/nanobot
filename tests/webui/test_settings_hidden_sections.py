"""Tests for WebUI hidden_settings_sections feature."""
from __future__ import annotations

import json

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_api import settings_payload


def test_settings_payload_includes_empty_hidden_sections_by_default(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    assert "webui" in payload
    assert payload["webui"]["hidden_settings_sections"] == []


def test_settings_payload_includes_configured_hidden_sections(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "webui": {
            "hiddenSettingsSections": ["advanced", "runtime", "models"],
        }
    })
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    hidden = payload["webui"]["hidden_settings_sections"]
    assert "advanced" in hidden
    assert "runtime" in hidden
    assert "models" in hidden
    assert len(hidden) == 3


def test_hidden_sections_config_accepts_unknown_keys_without_crash(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown section keys should be silently accepted — no validation error."""
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "webui": {
            "hiddenSettingsSections": ["nonexistent_section", "models"],
        }
    })
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    hidden = payload["webui"]["hidden_settings_sections"]
    assert "nonexistent_section" in hidden
    assert "models" in hidden


def test_hidden_sections_round_trips_through_save_and_load(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the hidden_settings_sections value survives save/load cycle."""
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "webui": {
            "hiddenSettingsSections": ["advanced", "runtime"],
        }
    })
    save_config(config, config_path)

    loaded = load_config(config_path)
    assert loaded.webui.hidden_settings_sections == ["advanced", "runtime"]

    # Verify the serialized JSON uses camelCase alias
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["webui"]["hiddenSettingsSections"] == ["advanced", "runtime"]


def test_hidden_sections_snake_case_alias_works(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """snake_case alias should work as input in config.json."""
    config = Config.model_validate({
        "webui": {
            "hidden_settings_sections": ["models", "image"],
        }
    })
    assert config.webui.hidden_settings_sections == ["models", "image"]


def test_save_config_omits_webui_key_when_at_defaults(
    tmp_path,
) -> None:
    """Default config should not serialize the webui key to avoid config noise."""
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert "webui" not in raw


def test_save_config_preserves_webui_key_when_configured(
    tmp_path,
) -> None:
    """Non-default hidden sections should be serialized."""
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "webui": {"hiddenSettingsSections": ["advanced"]},
    })
    save_config(config, config_path)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["webui"]["hiddenSettingsSections"] == ["advanced"]
