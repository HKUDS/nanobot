"""Tests for the Skywork provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_skywork_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "skywork")


def test_skywork_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "skywork" in specs
    skywork = specs["skywork"]
    assert skywork.backend == "openai_compat"
    assert skywork.env_key == "SKYWORK_API_KEY"
    assert ("APIFREE_API_KEY", "{api_key}") in skywork.env_extras
    assert skywork.display_name == "Skywork"
    assert skywork.is_gateway is True
    assert skywork.detect_by_base_keyword == "apifree.ai"
    assert skywork.default_api_base == "https://api.apifree.ai/v1"
    assert skywork.supports_max_completion_tokens is False


def test_find_by_name_skywork() -> None:
    spec = find_by_name("skywork")

    assert spec is not None
    assert spec.name == "skywork"


def test_skywork_model_auto_matches_with_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "skywork": {
                    "apiKey": "sky-key",
                },
            },
            "agents": {
                "defaults": {
                    "model": "skywork-ai/skyclaw-v1",
                },
            },
        }
    )

    assert config.get_provider_name("skywork-ai/skyclaw-v1") == "skywork"
    assert config.get_api_key("skywork-ai/skyclaw-v1") == "sky-key"
    assert config.get_api_base("skywork-ai/skyclaw-v1") == "https://api.apifree.ai/v1"


def test_skywork_preserves_model_id_and_uses_chat_completion_max_tokens() -> None:
    spec = find_by_name("skywork")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="sky-key",
            default_model="skywork-ai/skyclaw-v1",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="skywork-ai/skyclaw-v1",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "skywork-ai/skyclaw-v1"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs
