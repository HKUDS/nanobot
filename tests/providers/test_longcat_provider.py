"""Tests for the LongCat provider registration."""

from nanobot.config.schema import ProvidersConfig
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_longcat_config_field_exists():
    """ProvidersConfig should have a longcat field."""
    config = ProvidersConfig()
    assert hasattr(config, "longcat")


def test_longcat_provider_in_registry():
    """LongCat should be registered in the provider registry."""
    specs = {s.name: s for s in PROVIDERS}
    assert "longcat" in specs

    longcat = specs["longcat"]
    assert longcat.backend == "openai_compat"
    assert longcat.env_key == "LONGCAT_API_KEY"
    assert longcat.default_api_base == "https://api.longcat.chat/openai/v1"


def test_find_by_name_longcat():
    """find_by_name should resolve the LongCat provider."""
    spec = find_by_name("longcat")

    assert spec is not None
    assert spec.name == "longcat"
