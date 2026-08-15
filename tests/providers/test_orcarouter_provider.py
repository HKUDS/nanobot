"""Tests for the OrcaRouter provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.factory import make_provider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_orcarouter_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "orcarouter")


def test_orcarouter_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "orcarouter" in specs
    orcarouter = specs["orcarouter"]
    assert orcarouter.backend == "openai_compat"
    assert orcarouter.env_key == "ORCAROUTER_API_KEY"
    assert orcarouter.display_name == "OrcaRouter"
    assert orcarouter.is_gateway is True
    assert orcarouter.detect_by_key_prefix == "sk-orca-"
    assert orcarouter.detect_by_base_keyword == "orcarouter"
    assert orcarouter.default_api_base == "https://api.orcarouter.ai/v1"
    assert orcarouter.strip_model_prefix is False


def test_find_by_name_orcarouter() -> None:
    spec = find_by_name("orcarouter")

    assert spec is not None
    assert spec.name == "orcarouter"


def test_orcarouter_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "orcarouter": {
                "apiKey": "sk-orca-test-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "deepseek/deepseek-chat",
                "provider": "orcarouter",
            },
        },
    })

    assert config.get_provider_name("deepseek/deepseek-chat") == "orcarouter"
    assert config.get_api_key("deepseek/deepseek-chat") == "sk-orca-test-key"
    assert config.get_api_base("deepseek/deepseek-chat") == "https://api.orcarouter.ai/v1"


def test_orcarouter_gateway_routes_auto_model_when_configured() -> None:
    config = Config.model_validate({
        "providers": {
            "orcarouter": {
                "apiKey": "sk-orca-test-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "orcarouter/auto",
            },
        },
    })

    assert config.get_provider_name("orcarouter/auto") == "orcarouter"
    assert config.get_api_key("orcarouter/auto") == "sk-orca-test-key"
    assert config.get_api_base("orcarouter/auto") == "https://api.orcarouter.ai/v1"


def test_legacy_custom_provider_named_orcarouter_keeps_prefix_stripping() -> None:
    config = Config.model_validate({
        "providers": {
            "orcarouter": {
                "apiKey": "legacy-test-key",
                "apiBase": "https://legacy-gateway.example/v1",
            },
        },
        "agents": {
            "defaults": {
                "model": "orcarouter/custom-model",
                "provider": "orcarouter",
            },
        },
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert isinstance(provider, OpenAICompatProvider)
    assert provider.api_base == "https://legacy-gateway.example/v1"
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="orcarouter/custom-model",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )
    assert kwargs["model"] == "custom-model"


def test_orcarouter_preserves_model_api_id() -> None:
    spec = find_by_name("orcarouter")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="sk-orca-test-key",
            default_model="anthropic/claude-sonnet-4.6",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="anthropic/claude-sonnet-4.6",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "anthropic/claude-sonnet-4.6"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs
