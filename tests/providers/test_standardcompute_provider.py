"""Tests for the Standard Compute provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_standardcompute_config_field_exists() -> None:
    assert hasattr(ProvidersConfig(), "standardcompute")


def test_standardcompute_registry_contract() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "standardcompute" in specs
    spec = specs["standardcompute"]
    assert spec.backend == "openai_compat"
    assert spec.env_key == "STANDARDCOMPUTE_API_KEY"
    assert spec.display_name == "Standard Compute"
    assert spec.request_apis == ("chat_completions",)
    assert spec.is_gateway is True
    assert spec.detect_by_base_keyword == "stdcmpt"
    assert spec.default_api_base == "https://api.stdcmpt.com/v1"
    assert spec.strip_model_prefix is False
    # The gateway takes OpenAI's top-level reasoning_effort parameter.
    assert spec.gateway_reasoning_style == ""


def test_standardcompute_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"standardcompute": {"apiKey": "sc-key"}},
            "agents": {
                "defaults": {
                    "provider": "standardcompute",
                    "model": "anthropic/claude-sonnet-5.5",
                }
            },
        }
    )

    model = "anthropic/claude-sonnet-5.5"
    assert config.get_provider_name(model) == "standardcompute"
    assert config.get_api_key(model) == "sc-key"
    assert config.get_api_base(model) == "https://api.stdcmpt.com/v1"


def test_standardcompute_routing_model_matches_provider_keyword() -> None:
    config = Config.model_validate(
        {
            "providers": {"standardcompute": {"apiKey": "sc-key"}},
            "agents": {"defaults": {"model": "standardcompute"}},
        }
    )

    assert config.get_provider_name("standardcompute") == "standardcompute"
    assert config.get_api_base("standardcompute") == "https://api.stdcmpt.com/v1"


def test_standardcompute_preserves_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("standardcompute")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="sc-key",
            default_model="anthropic/claude-sonnet-5.5",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="anthropic/claude-sonnet-5.5",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "anthropic/claude-sonnet-5.5"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})
