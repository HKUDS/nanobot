"""Tests for the Mistral provider registration."""

from janniebot.config.schema import ProvidersConfig
from janniebot.providers.registry import PROVIDERS


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
