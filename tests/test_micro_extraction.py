"""Tests for micro-extraction (per-turn memory extraction)."""

from __future__ import annotations


def test_config_defaults():
    """Micro-extraction config fields exist with correct defaults."""
    from nanobot.config.schema import AgentConfig

    config = AgentConfig()
    assert config.micro_extraction_enabled is False
    assert config.micro_extraction_model is None
