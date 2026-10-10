"""Tests for the Cheaper Inference provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_cheaperinference_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "cheaperinference")


def test_cheaperinference_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "cheaperinference" in specs
    cheaperinference = specs["cheaperinference"]
    assert cheaperinference.backend == "openai_compat"
    assert cheaperinference.env_key == "CHEAPERINFERENCE_API_KEY"
    assert cheaperinference.display_name == "Cheaper Inference"
    assert cheaperinference.is_gateway is True
    assert cheaperinference.detect_by_key_prefix == "ci_live_"
    assert cheaperinference.detect_by_base_keyword == "cheaperinference"
    assert cheaperinference.default_api_base == "https://api.cheaperinference.com/v1"
    assert cheaperinference.strip_model_prefix is False
    assert cheaperinference.gateway_reasoning_style == ""


def test_find_by_name_cheaperinference() -> None:
    spec = find_by_name("cheaperinference")

    assert spec is not None
    assert spec.name == "cheaperinference"


def test_cheaperinference_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "cheaperinference": {
                "apiKey": "ci_live_test-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "gpt-5.4-mini",
                "provider": "cheaperinference",
            },
        },
    })

    assert config.get_provider_name("gpt-5.4-mini") == "cheaperinference"
    assert config.get_api_key("gpt-5.4-mini") == "ci_live_test-key"
    assert config.get_api_base("gpt-5.4-mini") == "https://api.cheaperinference.com/v1"


def test_cheaperinference_preserves_bare_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("cheaperinference")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="ci_live_test-key",
            default_model="gpt-5.4-mini",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="gpt-5.4-mini",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})
