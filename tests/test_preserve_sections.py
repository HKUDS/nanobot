"""Tests for the --preserve-sections flag in onboard command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.cli.commands import _onboard_plugins


class TestPreserveSections:
    """Tests for preserve_sections parameter in _onboard_plugins."""

    def test_default_adds_all_channels(self, tmp_path):
        """By default, all discovered channels should be added."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"channels": {"telegram": {"token": "test"}}}))

        # Mock discover_all to return multiple channels
        mock_channels = {
            "telegram": type("Channel", (), {"default_config": lambda: {"token": "", "allowed_users": []}}),
            "discord": type("Channel", (), {"default_config": lambda: {"token": "", "allowed_users": []}}),
            "whatsapp": type("Channel", (), {"default_config": lambda: {"token": "", "phone": ""}}),
        }

        with patch("nanobot.cli.commands.discover_all", return_value=mock_channels):
            _onboard_plugins(config_path, preserve_sections=False)

        data = json.loads(config_path.read_text())
        # All channels should be present
        assert "telegram" in data["channels"]
        assert "discord" in data["channels"]
        assert "whatsapp" in data["channels"]

    def test_preserve_sections_only_merges_existing(self, tmp_path):
        """With preserve_sections=True, only existing channels should get new fields."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"channels": {"telegram": {"token": "test"}}}))

        # Mock discover_all to return multiple channels
        mock_channels = {
            "telegram": type("Channel", (), {"default_config": lambda: {"token": "", "allowed_users": []}}),
            "discord": type("Channel", (), {"default_config": lambda: {"token": "", "allowed_users": []}}),
            "whatsapp": type("Channel", (), {"default_config": lambda: {"token": "", "phone": ""}}),
        }

        with patch("nanobot.cli.commands.discover_all", return_value=mock_channels):
            _onboard_plugins(config_path, preserve_sections=True)

        data = json.loads(config_path.read_text())
        # Only telegram should be present (it was already there)
        assert "telegram" in data["channels"]
        # New channels should NOT be added
        assert "discord" not in data["channels"]
        assert "whatsapp" not in data["channels"]

    def test_preserve_sections_merges_new_fields(self, tmp_path):
        """preserve_sections should still merge new fields into existing channels."""
        config_path = tmp_path / "config.json"
        # telegram has token but not allowed_users
        config_path.write_text(json.dumps({"channels": {"telegram": {"token": "my_token"}}}))

        mock_channels = {
            "telegram": type(
                "Channel",
                (),
                {"default_config": lambda: {"token": "", "allowed_users": [], "enabled": True}},
            ),
        }

        with patch("nanobot.cli.commands.discover_all", return_value=mock_channels):
            _onboard_plugins(config_path, preserve_sections=True)

        data = json.loads(config_path.read_text())
        # Existing value preserved
        assert data["channels"]["telegram"]["token"] == "my_token"
        # New fields merged in
        assert "allowed_users" in data["channels"]["telegram"]
        assert "enabled" in data["channels"]["telegram"]

    def test_preserve_sections_empty_channels(self, tmp_path):
        """preserve_sections with no existing channels should result in no channels."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"channels": {}}))

        mock_channels = {
            "telegram": type("Channel", (), {"default_config": lambda: {"token": ""}}),
            "discord": type("Channel", (), {"default_config": lambda: {"token": ""}}),
        }

        with patch("nanobot.cli.commands.discover_all", return_value=mock_channels):
            _onboard_plugins(config_path, preserve_sections=True)

        data = json.loads(config_path.read_text())
        # No channels should be added
        assert data["channels"] == {}

    def test_preserve_sections_no_channels_key(self, tmp_path):
        """preserve_sections with no channels key should result in empty channels."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))

        mock_channels = {
            "telegram": type("Channel", (), {"default_config": lambda: {"token": ""}}),
        }

        with patch("nanobot.cli.commands.discover_all", return_value=mock_channels):
            _onboard_plugins(config_path, preserve_sections=True)

        data = json.loads(config_path.read_text())
        # Channels key created but empty
        assert data["channels"] == {}