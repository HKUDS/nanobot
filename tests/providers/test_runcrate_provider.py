"""Tests for the Runcrate provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_runcrate_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "runcrate")


def test_runcrate_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "runcrate" in specs
    runcrate = specs["runcrate"]
    assert runcrate.backend == "openai_compat"
    assert runcrate.env_key == "RUNCRATE_API_KEY"
    assert runcrate.display_name == "Runcrate"
    assert runcrate.is_gateway is True
    assert runcrate.detect_by_base_keyword == "runcrate"
    assert runcrate.default_api_base == "https://api.runcrate.ai/v1"
    assert runcrate.strip_model_prefix is False


def test_find_by_name_runcrate() -> None:
    spec = find_by_name("runcrate")

    assert spec is not None
    assert spec.name == "runcrate"


def test_runcrate_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "runcrate": {
                "apiKey": "runcrate-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "deepseek-ai/DeepSeek-V4.1-Flash",
                "provider": "runcrate",
            },
        },
    })

    assert config.get_provider_name("deepseek-ai/DeepSeek-V4.1-Flash") == "runcrate"
    assert config.get_api_key("deepseek-ai/DeepSeek-V4.1-Flash") == "runcrate-key"
    assert config.get_api_base("deepseek-ai/DeepSeek-V4.1-Flash") == "https://api.runcrate.ai/v1"


def test_runcrate_gateway_routes_org_prefixed_models_when_configured() -> None:
    config = Config.model_validate({
        "providers": {
            "runcrate": {
                "apiKey": "runcrate-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "deepseek-ai/DeepSeek-V4.1-Flash",
            },
        },
    })

    assert config.get_provider_name("deepseek-ai/DeepSeek-V4.1-Flash") == "runcrate"
    assert config.get_api_key("deepseek-ai/DeepSeek-V4.1-Flash") == "runcrate-key"
    assert config.get_api_base("deepseek-ai/DeepSeek-V4.1-Flash") == "https://api.runcrate.ai/v1"


def test_runcrate_preserves_model_api_id() -> None:
    spec = find_by_name("runcrate")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="runcrate-key",
            default_model="deepseek-ai/DeepSeek-V4.1-Flash",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="deepseek-ai/DeepSeek-V4.1-Flash",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "deepseek-ai/DeepSeek-V4.1-Flash"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs
