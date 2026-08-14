"""Tests for the Eden AI provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_edenai_config_field_exists() -> None:
    assert hasattr(ProvidersConfig(), "edenai")


def test_edenai_registry_contract() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "edenai" in specs
    edenai = specs["edenai"]
    assert edenai.backend == "openai_compat"
    assert edenai.env_key == "EDENAI_API_KEY"
    assert edenai.display_name == "Eden AI"
    assert edenai.is_gateway is True
    assert edenai.detect_by_base_keyword == "edenai"
    assert edenai.default_api_base == "https://api.edenai.run/v3"
    assert edenai.strip_model_prefix is False
    # Eden accepts OpenAI's top-level reasoning_effort parameter. Do not add
    # OpenRouter's separate {"reasoning": {"effort": ...}} request shape.
    assert edenai.gateway_reasoning_style == ""


def test_edenai_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"edenai": {"apiKey": "eden-key"}},
            "agents": {
                "defaults": {
                    "provider": "edenai",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
        }
    )

    model = "anthropic/claude-sonnet-4-5"
    assert config.get_provider_name(model) == "edenai"
    assert config.get_api_key(model) == "eden-key"
    assert config.get_api_base(model) == "https://api.edenai.run/v3"


def test_edenai_preserves_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("edenai")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="eden-key",
            default_model="anthropic/claude-sonnet-4-5",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="anthropic/claude-sonnet-4-5",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "anthropic/claude-sonnet-4-5"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})
