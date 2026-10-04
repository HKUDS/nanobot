"""Tests for the Opper provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_opper_config_field_exists() -> None:
    assert hasattr(ProvidersConfig(), "opper")


def test_opper_registry_contract() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "opper" in specs
    opper = specs["opper"]
    assert opper.backend == "openai_compat"
    assert opper.env_key == "OPPER_API_KEY"
    assert opper.display_name == "Opper"
    assert opper.is_gateway is True
    assert opper.detect_by_base_keyword == "opper"
    assert opper.default_api_base == "https://api.opper.ai/v3/compat"
    assert opper.strip_model_prefix is False
    # Opper accepts OpenAI's top-level reasoning_effort parameter. Do not add
    # OpenRouter's separate {"reasoning": {"effort": ...}} request shape.
    assert opper.gateway_reasoning_style == ""


def test_find_by_name_opper() -> None:
    spec = find_by_name("opper")

    assert spec is not None
    assert spec.name == "opper"


def test_opper_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"opper": {"apiKey": "opper-key"}},
            "agents": {
                "defaults": {
                    "provider": "opper",
                    "model": "claude-sonnet-4-6",
                }
            },
        }
    )

    model = "claude-sonnet-4-6"
    assert config.get_provider_name(model) == "opper"
    assert config.get_api_key(model) == "opper-key"
    assert config.get_api_base(model) == "https://api.opper.ai/v3/compat"


def test_opper_gateway_routes_unprefixed_models_when_configured() -> None:
    config = Config.model_validate(
        {
            "providers": {"opper": {"apiKey": "opper-key"}},
            "agents": {"defaults": {"model": "claude-sonnet-4-6"}},
        }
    )

    assert config.get_provider_name("claude-sonnet-4-6") == "opper"


def test_opper_preserves_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("opper")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="opper-key",
            default_model="claude-sonnet-4-6",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        # "provider/model" pins one upstream provider or region and must be
        # forwarded unchanged, like the bare pool name.
        model="azure/gpt-5.5",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "azure/gpt-5.5"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})
