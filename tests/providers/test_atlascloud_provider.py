"""Tests for the Atlas Cloud provider registration."""

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_atlascloud_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "atlascloud")


def test_atlascloud_spec_uses_openai_compatible_gateway() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}
    atlascloud = specs["atlascloud"]
    model_ids = {model.id for model in atlascloud.builtin_models}

    assert atlascloud.backend == "openai_compat"
    assert atlascloud.env_key == "ATLASCLOUD_API_KEY"
    assert atlascloud.display_name == "Atlas Cloud"
    assert atlascloud.model_catalog == "builtin"
    assert atlascloud.is_gateway is True
    assert atlascloud.detect_by_base_keyword == "atlascloud.ai"
    assert atlascloud.default_api_base == "https://api.atlascloud.ai/v1"
    assert "atlascloud" in atlascloud.strip_model_prefixes
    assert "qwen/qwen3.5-flash" in model_ids
    assert "deepseek-ai/deepseek-v4-pro" in model_ids


def test_find_by_name_atlascloud_provider() -> None:
    canonical = find_by_name("atlascloud")
    assert canonical is not None
    assert canonical.name == "atlascloud"


def test_atlascloud_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"atlascloud": {"apiKey": "atlascloud-key"}},
            "agents": {
                "defaults": {
                    "provider": "atlascloud",
                    "model": "qwen/qwen3.5-flash",
                }
            },
        }
    )

    assert config.get_provider_name() == "atlascloud"
    assert config.get_api_key() == "atlascloud-key"
    assert config.get_api_base() == "https://api.atlascloud.ai/v1"


def test_atlascloud_prefix_is_stripped_before_request() -> None:
    provider = OpenAICompatProvider(
        api_key=None,
        default_model="atlascloud/qwen/qwen3.5-flash",
        spec=find_by_name("atlascloud"),
    )
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="atlascloud/qwen/qwen3.5-flash",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "qwen/qwen3.5-flash"


def test_atlascloud_native_model_ids_are_preserved() -> None:
    provider = OpenAICompatProvider(
        api_key=None,
        default_model="qwen/qwen3.5-flash",
        spec=find_by_name("atlascloud"),
    )
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="qwen/qwen3.5-flash",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "qwen/qwen3.5-flash"
