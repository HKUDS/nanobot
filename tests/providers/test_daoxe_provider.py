"""Tests for the DaoXE provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_daoxe_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "daoxe")


def test_daoxe_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "daoxe" in specs
    daoxe = specs["daoxe"]
    assert daoxe.backend == "openai_compat"
    assert daoxe.env_key == "DAOXE_API_KEY"
    assert daoxe.display_name == "DaoXE"
    assert daoxe.is_gateway is True
    assert daoxe.detect_by_base_keyword == "daoxe.com"
    assert daoxe.default_api_base == "https://api.daoxe.com/v1"
    assert daoxe.strip_model_prefix is False
    assert daoxe.builtin_models == ()


def test_find_by_name_daoxe() -> None:
    spec = find_by_name("daoxe")

    assert spec is not None
    assert spec.name == "daoxe"


def test_daoxe_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate({
        "providers": {
            "daoxe": {
                "apiKey": "daoxe-test-key",
            },
        },
        "agents": {
            "defaults": {
                "model": "gpt-4o",
                "provider": "daoxe",
            },
        },
    })

    assert config.get_provider_name("gpt-4o") == "daoxe"
    assert config.get_api_key("gpt-4o") == "daoxe-test-key"
    assert config.get_api_base("gpt-4o") == "https://api.daoxe.com/v1"


def test_daoxe_preserves_model_api_id() -> None:
    spec = find_by_name("daoxe")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="daoxe-test-key",
            default_model="some-account-model",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="some-account-model",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "some-account-model"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs
