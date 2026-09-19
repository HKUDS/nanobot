"""Tests for the IO Intelligence (io.net) provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_ionet_config_field_exists() -> None:
    assert hasattr(ProvidersConfig(), "ionet")


def test_ionet_registry_contract() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "ionet" in specs
    ionet = specs["ionet"]
    assert ionet.backend == "openai_compat"
    assert ionet.env_key == "IONET_API_KEY"
    assert ionet.display_name == "IO Intelligence"
    assert ionet.is_gateway is True
    assert ionet.detect_by_base_keyword == "intelligence.io.solutions"
    assert ionet.default_api_base == "https://api.intelligence.io.solutions/api/v1"
    assert ionet.strip_model_prefix is False
    assert ionet.strip_model_prefixes == ("ionet",)
    # OpenAI-style top-level reasoning_effort; no separate gateway reasoning shape.
    assert ionet.gateway_reasoning_style == ""


def test_ionet_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"ionet": {"apiKey": "ionet-key"}},
            "agents": {
                "defaults": {
                    "provider": "ionet",
                    "model": "meta-llama/Llama-3.3-70B-Instruct",
                }
            },
        }
    )

    model = "meta-llama/Llama-3.3-70B-Instruct"
    assert config.get_provider_name(model) == "ionet"
    assert config.get_api_key(model) == "ionet-key"
    assert config.get_api_base(model) == "https://api.intelligence.io.solutions/api/v1"


def test_ionet_gateway_routes_unprefixed_models_when_configured() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "ionet": {
                    "apiKey": "ionet-key",
                },
            },
            "agents": {
                "defaults": {
                    "model": "Llama-3.3-70B-Instruct",
                },
            },
        }
    )

    model = "Llama-3.3-70B-Instruct"
    assert config.get_provider_name(model) == "ionet"
    assert config.get_api_key(model) == "ionet-key"
    assert config.get_api_base(model) == "https://api.intelligence.io.solutions/api/v1"


def test_ionet_preserves_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("ionet")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="ionet-key",
            default_model="meta-llama/Llama-3.3-70B-Instruct",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="meta-llama/Llama-3.3-70B-Instruct",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "meta-llama/Llama-3.3-70B-Instruct"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})


def test_ionet_strips_own_provider_prefix() -> None:
    spec = find_by_name("ionet")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="ionet-key",
            default_model="meta-llama/Llama-3.3-70B-Instruct",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="ionet/meta-llama/Llama-3.3-70B-Instruct",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "meta-llama/Llama-3.3-70B-Instruct"
