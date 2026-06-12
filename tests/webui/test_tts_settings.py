"""Tests for TTS settings in the WebUI settings API."""

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_api import (
    WebUISettingsError,
    settings_payload,
    update_tts_settings,
)


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.openai.api_key = "sk-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    return config


class TestTTSSettingsPayload:
    def test_tts_section_present(self, fresh_config):
        payload = settings_payload()
        assert "tts" in payload
        tts = payload["tts"]
        assert tts["enabled"] is True
        assert tts["provider"] == "openai"
        assert tts["model"] == "tts-1"
        assert tts["voice"] == "alloy"
        assert tts["speed"] == 1.0
        assert tts["max_char_length"] == 4096
        assert "providers" in tts
        provider_names = [p["name"] for p in tts["providers"]]
        assert "openai" in provider_names
        assert "groq" in provider_names
        assert "elevenlabs" in provider_names


class TestUpdateTTSSettings:
    def test_update_provider(self, fresh_config):
        payload = update_tts_settings({"provider": ["groq"]})
        assert payload["tts"]["provider"] == "groq"

    def test_update_voice(self, fresh_config):
        payload = update_tts_settings({"voice": ["nova"]})
        assert payload["tts"]["voice"] == "nova"

    def test_update_speed(self, fresh_config):
        payload = update_tts_settings({"speed": ["1.5"]})
        assert payload["tts"]["speed"] == 1.5

    def test_update_model(self, fresh_config):
        payload = update_tts_settings({"model": ["tts-1-hd"]})
        assert payload["tts"]["model"] == "tts-1-hd"

    def test_update_max_char_length(self, fresh_config):
        payload = update_tts_settings({"max_char_length": ["8192"]})
        assert payload["tts"]["max_char_length"] == 8192

    def test_disable_tts(self, fresh_config):
        payload = update_tts_settings({"enabled": ["false"]})
        assert payload["tts"]["enabled"] is False

    def test_unknown_provider_raises(self, fresh_config):
        with pytest.raises(WebUISettingsError, match="unknown TTS provider"):
            update_tts_settings({"provider": ["nonexistent"]})

    def test_speed_out_of_range_raises(self, fresh_config):
        with pytest.raises(WebUISettingsError, match="speed"):
            update_tts_settings({"speed": ["5.0"]})

    def test_max_char_length_out_of_range_raises(self, fresh_config):
        with pytest.raises(WebUISettingsError, match="max_char_length"):
            update_tts_settings({"max_char_length": ["0"]})

    def test_eleven_alias_resolves(self, fresh_config):
        payload = update_tts_settings({"provider": ["eleven"]})
        assert payload["tts"]["provider"] == "elevenlabs"
