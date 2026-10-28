"""Tests for the aimlapi.com provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_aimlapi_config_field_exists() -> None:
    assert hasattr(ProvidersConfig(), "aiml_api")


def test_aimlapi_registry_contract() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "aiml_api" in specs
    aimlapi = specs["aiml_api"]
    assert aimlapi.backend == "openai_compat"
    assert aimlapi.env_key == "AIMLAPI_API_KEY"
    assert aimlapi.display_name == "aimlapi.com"
    assert aimlapi.is_gateway is True
    assert aimlapi.detect_by_base_keyword == "aimlapi"
    assert aimlapi.default_api_base == "https://api.aimlapi.com/v1"
    assert aimlapi.strip_model_prefix is False
    # aimlapi.com accepts OpenAI's top-level reasoning_effort parameter. Do not add
    # OpenRouter's separate {"reasoning": {"effort": ...}} request shape.
    assert aimlapi.gateway_reasoning_style == ""


def test_aimlapi_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"aimlApi": {"apiKey": "aimlapi-key"}},
            "agents": {
                "defaults": {
                    "provider": "aiml_api",
                    "model": "openai/gpt-5",
                }
            },
        }
    )

    model = "openai/gpt-5"
    assert config.get_provider_name(model) == "aiml_api"
    assert config.get_api_key(model) == "aimlapi-key"
    assert config.get_api_base(model) == "https://api.aimlapi.com/v1"


def test_aimlapi_preserves_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("aiml_api")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="aimlapi-key",
            default_model="openai/gpt-5",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="openai/gpt-5",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "openai/gpt-5"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})
