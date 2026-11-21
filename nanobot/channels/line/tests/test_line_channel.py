"""Tests for LINE channel manifest and settings."""

from nanobot.channels.line.manifest import PLUGIN, SETUP_SPEC
from nanobot.channels.line.runtime import LineSettings


def test_plugin_name():
    assert PLUGIN.name == "line"
    assert PLUGIN.display_name == "LINE"


def test_setup_spec_fields():
    field_names = {f.name for f in SETUP_SPEC.fields}
    assert "channelAccessToken" in field_names
    assert "channelSecret" in field_names
    assert "allowFrom" in field_names


def test_setup_spec_required():
    assert "channelAccessToken" in SETUP_SPEC.required
    assert "channelSecret" in SETUP_SPEC.required


def test_settings_validation():
    s = LineSettings(channelAccessToken="test-token", channelSecret="test-secret")
    assert s.channel_access_token == "test-token"
    assert s.channel_secret == "test-secret"


def test_settings_token_non_empty():
    try:
        LineSettings(channelAccessToken="  ", channelSecret="x")
        assert False, "should have raised"
    except Exception:
        pass
