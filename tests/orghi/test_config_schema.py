"""Tests for CursorConfig."""

from pathlib import Path

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_config_loads_cursor_api_key_from_json() -> None:
    data = {"tools": {"cursor": {"apiKey": "sk-test"}}}
    config = Config.model_validate(data)
    assert config.tools.cursor.api_key == "sk-test"


def test_config_cursor_default_empty() -> None:
    config = Config()
    assert config.tools.cursor.api_key == ""


def test_config_save_roundtrip_cursor(tmp_path: Path) -> None:
    config = Config()
    config.tools.cursor.api_key = "sk-roundtrip"
    save_config(config, tmp_path / "config.json")

    loaded = load_config(tmp_path / "config.json")
    assert loaded.tools.cursor.api_key == "sk-roundtrip"
