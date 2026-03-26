"""Tests for micro-extraction (per-turn memory extraction)."""

from __future__ import annotations

from nanobot.memory.write.micro_extractor import _MICRO_EXTRACT_TOOL


def test_config_defaults():
    """Micro-extraction config fields exist with correct defaults."""
    from nanobot.config.schema import AgentConfig

    config = AgentConfig()
    assert config.micro_extraction_enabled is False
    assert config.micro_extraction_model is None


def test_tool_schema_has_required_fields():
    """Tool schema requires events array."""
    schema = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]
    assert "events" in schema["properties"]
    assert "events" in schema["required"]


def test_tool_schema_event_types():
    """Event type enum has all 6 valid types."""
    items = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]["properties"]["events"]["items"]
    expected = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    assert set(items["properties"]["type"]["enum"]) == expected


def test_tool_schema_event_required_fields():
    """Each event requires type and summary."""
    items = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]["properties"]["events"]["items"]
    assert set(items["required"]) == {"type", "summary"}
