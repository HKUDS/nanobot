"""Tests for SubAgentConfig — shared sub-agent execution parameters."""

from __future__ import annotations

from pathlib import Path


def test_sub_agent_config_defaults():
    """SubAgentConfig has sensible defaults for optional fields."""
    from nanobot.config.sub_agent import SubAgentConfig

    cfg = SubAgentConfig(workspace=Path("/tmp/test"), model="test-model")
    assert cfg.workspace == Path("/tmp/test")
    assert cfg.model == "test-model"
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 4096


def test_sub_agent_config_custom_values():
    """SubAgentConfig accepts custom values for all fields."""
    from nanobot.config.sub_agent import SubAgentConfig

    cfg = SubAgentConfig(
        workspace=Path("/tmp/ws"),
        model="gpt-4o",
        temperature=0.3,
        max_tokens=2048,
    )
    assert cfg.temperature == 0.3
    assert cfg.max_tokens == 2048


def test_sub_agent_config_from_dict():
    """SubAgentConfig can be constructed from a dict (JSON-compatible)."""
    from nanobot.config.sub_agent import SubAgentConfig

    cfg = SubAgentConfig.model_validate(
        {
            "workspace": "/tmp/ws",
            "model": "gpt-4o",
            "temperature": 0.3,
            "max_tokens": 2048,
        }
    )
    assert cfg.temperature == 0.3
    assert cfg.max_tokens == 2048
