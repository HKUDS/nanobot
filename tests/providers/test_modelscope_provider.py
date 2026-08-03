"""Tests for the ModelScope (魔搭) provider registration."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_modelscope_config_field_exists() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "modelscope")


def test_modelscope_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "modelscope" in specs
    ms = specs["modelscope"]
    assert ms.backend == "openai_compat"
    assert ms.env_key == "MODELSCOPE_API_KEY"
    assert ms.display_name == "ModelScope"
    assert ms.is_gateway is True
    assert ms.default_api_base == "https://api-inference.modelscope.cn/v1"
    assert ms.strip_model_prefixes == ("modelscope",)
    assert ms.thinking_style == "enable_thinking"


def test_find_by_name_modelscope() -> None:
    spec = find_by_name("modelscope")

    assert spec is not None
    assert spec.name == "modelscope"


def test_modelscope_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "modelscope": {
                    "apiKey": "ms-token",
                },
            },
            "agents": {
                "defaults": {
                    "model": "Qwen/Qwen3.5-35B-A3B",
                    "provider": "modelscope",
                },
            },
        }
    )

    assert config.get_provider_name("Qwen/Qwen3.5-35B-A3B") == "modelscope"
    assert config.get_api_key("Qwen/Qwen3.5-35B-A3B") == "ms-token"
    assert config.get_api_base("Qwen/Qwen3.5-35B-A3B") == "https://api-inference.modelscope.cn/v1"


def test_modelscope_keyword_matches_prefixed_model() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "modelscope": {
                    "apiKey": "ms-token",
                },
            },
            "agents": {
                "defaults": {
                    "model": "modelscope/Qwen/Qwen3.5-35B-A3B",
                },
            },
        }
    )

    assert config.get_provider_name("modelscope/Qwen/Qwen3.5-35B-A3B") == "modelscope"
    assert config.get_api_key("modelscope/Qwen/Qwen3.5-35B-A3B") == "ms-token"


def test_modelscope_strips_prefix_in_request_model() -> None:
    spec = find_by_name("modelscope")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="ms-token",
            default_model="modelscope/Qwen/Qwen3.5-35B-A3B",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="modelscope/Qwen/Qwen3.5-35B-A3B",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    # strip_model_prefixes removes "modelscope/" → "Qwen/Qwen3.5-35B-A3B"
    assert kwargs["model"] == "Qwen/Qwen3.5-35B-A3B"
    assert kwargs["max_tokens"] == 1024
    assert "max_completion_tokens" not in kwargs


def test_modelscope_routes_unprefixed_models_when_configured() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "modelscope": {
                    "apiKey": "ms-token",
                    "apiBase": "https://api-inference.modelscope.cn/v1",
                },
            },
            "agents": {
                "defaults": {
                    "model": "Qwen/Qwen3.5-35B-A3B",
                },
            },
        }
    )

    name = config.get_provider_name("Qwen/Qwen3.5-35B-A3B")
    assert name == "modelscope"
