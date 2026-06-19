"""Tests for the Novita AI provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_novita_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "novita")


def test_novita_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "novita" in specs
    novita = specs["novita"]
    assert novita.backend == "openai_compat"
    assert novita.env_key == "NOVITA_API_KEY"
    assert novita.display_name == "Novita AI"
    assert novita.is_gateway is True
    assert novita.detect_by_base_keyword == "novita"
    assert novita.default_api_base == "https://api.novita.ai/openai"
    assert novita.strip_model_prefix is False


def test_find_by_name_novita() -> None:
    spec = find_by_name("novita")

    assert spec is not None
    assert spec.name == "novita"


def test_novita_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "novita": {
                "apiKey": "novita-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "deepseek-v4-pro",
                "provider": "novita",
            },
        },
    })

    assert config.get_provider_name("deepseek-v4-pro") == "novita"
    assert config.get_api_key("deepseek-v4-pro") == "novita-key"
    assert config.get_api_base("deepseek-v4-pro") == "https://api.novita.ai/openai"


def test_novita_gateway_routes_unprefixed_models_when_configured() -> None:
    config = Config.model_validate({
        "providers": {
            "novita": {
                "apiKey": "novita-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "deepseek-v4-pro",
            },
        },
    })

    assert config.get_provider_name("deepseek-v4-pro") == "novita"
    assert config.get_api_key("deepseek-v4-pro") == "novita-key"
    assert config.get_api_base("deepseek-v4-pro") == "https://api.novita.ai/openai"


def test_novita_preserves_model_api_id() -> None:
    spec = find_by_name("novita")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="novita-key",
            default_model="deepseek-v4-pro",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="deepseek-v4-pro",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "deepseek-v4-pro"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs
