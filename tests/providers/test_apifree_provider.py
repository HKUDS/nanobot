"""Tests for the APIFree provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_apifree_config_field_exists() -> None:
    config = ProvidersConfig()
    assert hasattr(config, "apifree")


def test_apifree_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}
    assert "apifree" in specs

    apifree = specs["apifree"]
    assert apifree.backend == "openai_compat"
    assert apifree.env_key == "APIFREE_API_KEY"
    assert apifree.display_name == "APIFree"
    assert apifree.default_api_base == "https://api.apifree.ai/agent/v1"


def test_find_by_name_accepts_apifree_spellings() -> None:
    spec = find_by_name("apifree")
    assert spec is not None


def test_apifree_model_auto_matches_with_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "apifree": {
                    "apiKey": "apifree-key",
                },
            },
            "agents": {
                "defaults": {
                    "model": "skywork-ai/skyclaw-v1",
                },
            },
        }
    )

    assert config.get_provider_name("skywork-ai/skyclaw-v1") == "apifree"
    assert config.get_api_key("skywork-ai/skyclaw-v1") == "apifree-key"
    assert config.get_api_base("skywork-ai/skyclaw-v1") == "https://api.apifree.ai/agent/v1"


def test_apifree_preserves_official_model_name() -> None:
    spec = find_by_name("apifree")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="apifree-key",
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
