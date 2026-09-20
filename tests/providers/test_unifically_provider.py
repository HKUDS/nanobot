"""Tests for the Unifically provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_unifically_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "unifically")


def test_unifically_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "unifically" in specs
    unifically = specs["unifically"]
    assert unifically.backend == "openai_compat"
    assert unifically.env_key == "UNIFICALLY_API_KEY"
    assert unifically.display_name == "Unifically"
    assert unifically.is_gateway is True
    assert unifically.detect_by_base_keyword == "unifically"
    assert unifically.default_api_base == "https://api.unifically.com/v1"
    assert unifically.strip_model_prefix is False


def test_find_by_name_unifically() -> None:
    spec = find_by_name("unifically")

    assert spec is not None
    assert spec.name == "unifically"


def test_unifically_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "unifically": {
                "apiKey": "unifically-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "google/gemini-3.5-flash",
                "provider": "unifically",
            },
        },
    })

    assert config.get_provider_name("google/gemini-3.5-flash") == "unifically"
    assert config.get_api_key("google/gemini-3.5-flash") == "unifically-key"
    assert config.get_api_base("google/gemini-3.5-flash") == "https://api.unifically.com/v1"


def test_unifically_gateway_routes_unprefixed_models_when_configured() -> None:
    config = Config.model_validate({
        "providers": {
            "unifically": {
                "apiKey": "unifically-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "google/gemini-3.5-flash",
            },
        },
    })

    assert config.get_provider_name("google/gemini-3.5-flash") == "unifically"
    assert config.get_api_key("google/gemini-3.5-flash") == "unifically-key"
    assert config.get_api_base("google/gemini-3.5-flash") == "https://api.unifically.com/v1"


def test_unifically_preserves_model_api_id() -> None:
    spec = find_by_name("unifically")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="unifically-key",
            default_model="google/gemini-3.5-flash",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="google/gemini-3.5-flash",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "google/gemini-3.5-flash"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs
