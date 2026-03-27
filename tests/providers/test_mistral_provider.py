"""Tests for the Mistral provider registration."""

from nanobot.config.schema import ProvidersConfig
from nanobot.providers.registry import PROVIDERS


def test_mistral_config_field_exists():
    """ProvidersConfig should have a mistral field."""
    config = ProvidersConfig()
    assert hasattr(config, "mistral")


def test_mistral_provider_in_registry():
    """Mistral should be registered in the provider registry."""
    specs = {s.name: s for s in PROVIDERS}
    assert "mistral" in specs

    mistral = specs["mistral"]
    assert mistral.env_key == "MISTRAL_API_KEY"
    assert mistral.default_api_base == "https://api.mistral.ai/v1"


def test_opencode_config_field_exists():
    """ProvidersConfig should have an opencode field."""
    config = ProvidersConfig()
    assert hasattr(config, "opencode")


def test_opencode_provider_in_registry():
    """OpenCode should be registered in the provider registry."""
    specs = {s.name: s for s in PROVIDERS}
    assert "opencode" in specs

    opencode = specs["opencode"]
    assert opencode.backend == "opencode_cli"
    assert opencode.is_direct is True
