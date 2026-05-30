"""Tests for the MiniMax Anthropic provider registration."""

from nanobot.config.schema import ProvidersConfig
from nanobot.providers.registry import PROVIDERS


def test_minimax_anthropic_config_field_exists():
    """ProvidersConfig should expose a minimax_anthropic field."""
    config = ProvidersConfig()
    assert hasattr(config, "minimax_anthropic")


def test_minimax_anthropic_provider_in_registry():
    """MiniMax Anthropic endpoint should be registered with Anthropic backend."""
    specs = {s.name: s for s in PROVIDERS}
    assert "minimax_anthropic" in specs

    minimax_anthropic = specs["minimax_anthropic"]
    assert minimax_anthropic.env_key == "MINIMAX_API_KEY"
    assert minimax_anthropic.backend == "anthropic"
    assert minimax_anthropic.default_api_base == "https://api.minimax.io/anthropic"
