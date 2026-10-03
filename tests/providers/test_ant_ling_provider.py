"""Tests for the Ant Ling provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_ant_ling_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "ant_ling")


def test_ant_ling_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "ant_ling" in specs
    ant_ling = specs["ant_ling"]
    assert ant_ling.backend == "openai_compat"
    assert ant_ling.env_key == "ANT_LING_API_KEY"
    assert ant_ling.display_name == "Ant Ling"
    assert ant_ling.default_api_base == "https://api.ant-ling.com/v1"


def test_find_by_name_accepts_ant_ling_spellings() -> None:
    spec = find_by_name("ant_ling")

    assert spec is not None
    assert find_by_name("ant-ling") is spec
    assert find_by_name("antLing") is spec


def test_ant_ling_model_auto_matches_with_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "antLing": {
                "apiKey": "ling-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "Ling-2.6-flash",
            },
        },
    })

    assert config.get_provider_name("Ling-2.6-flash") == "ant_ling"
    assert config.get_api_key("Ling-2.6-flash") == "ling-key"
    assert config.get_api_base("Ling-2.6-flash") == "https://api.ant-ling.com/v1"


def test_ant_ling_preserves_official_model_name() -> None:
    spec = find_by_name("ant_ling")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="ling-key",
            default_model="Ling-2.6-flash",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="Ling-2.6-flash",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "Ling-2.6-flash"
