"""Tests for the aimlapi.com provider registration."""

import re
from unittest.mock import patch

from nanobot.config.schema import Config, ProviderConfig, ProvidersConfig
from nanobot.providers.factory import _provider_extra_headers
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name

# The gateway silently drops a malformed partner id, so only a test catches a typo.
PARTNER_ID_PATTERN = re.compile(r"^part_[A-Za-z0-9]{1,64}$")
SOURCE_PATTERN = re.compile(r"^(web|agent|mcp)/[a-z0-9-]{1,32}$")


def test_aimlapi_config_field_exists() -> None:
    assert hasattr(ProvidersConfig(), "aimlapi")


def test_aimlapi_registry_contract() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    assert "aimlapi" in specs
    aimlapi = specs["aimlapi"]
    assert aimlapi.backend == "openai_compat"
    assert aimlapi.env_key == "AIMLAPI_API_KEY"
    assert aimlapi.display_name == "aimlapi.com"
    assert aimlapi.is_gateway is True
    assert aimlapi.detect_by_base_keyword == "aimlapi"
    assert aimlapi.default_api_base == "https://api.aimlapi.com/v1"
    assert aimlapi.strip_model_prefix is False
    # aimlapi.com accepts OpenAI's top-level reasoning_effort parameter. Do not add
    # OpenRouter's separate {"reasoning": {"effort": ...}} request shape.
    assert aimlapi.gateway_reasoning_style == ""


def test_aimlapi_forced_provider_uses_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {"aimlapi": {"apiKey": "aimlapi-key"}},
            "agents": {
                "defaults": {
                    "provider": "aimlapi",
                    "model": "openai/gpt-5",
                }
            },
        }
    )

    model = "openai/gpt-5"
    assert config.get_provider_name(model) == "aimlapi"
    assert config.get_api_key(model) == "aimlapi-key"
    assert config.get_api_base(model) == "https://api.aimlapi.com/v1"


def test_aimlapi_preserves_model_id_and_reasoning_effort() -> None:
    spec = find_by_name("aimlapi")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="aimlapi-key",
            default_model="openai/gpt-5",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="openai/gpt-5",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["model"] == "openai/gpt-5"
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs.get("extra_body", {})


def test_aimlapi_default_headers_identify_nanobot() -> None:
    spec = find_by_name("aimlapi")

    assert spec is not None
    headers = _provider_extra_headers(spec, ProviderConfig())
    assert headers == {
        "HTTP-Referer": "https://github.com/HKUDS/nanobot",
        "X-Title": "nanobot",
        "X-AIMLAPI-Source": "agent/hkuds-nanobot",
        "X-AIMLAPI-Partner-ID": "part_TcTxHfamJ2kkNiFsYzEVELTy",
    }
    assert PARTNER_ID_PATTERN.match(headers["X-AIMLAPI-Partner-ID"])
    assert SOURCE_PATTERN.match(headers["X-AIMLAPI-Source"])


def test_aimlapi_default_headers_are_scoped_to_this_provider() -> None:
    for spec in PROVIDERS:
        if spec.name == "aimlapi":
            continue
        assert not any(
            name.lower().startswith("x-aimlapi-") for name, _ in spec.default_extra_headers
        )


def test_aimlapi_user_headers_win_without_mutating_the_spec() -> None:
    spec = find_by_name("aimlapi")
    assert spec is not None
    before = dict(spec.default_extra_headers)

    provider = ProviderConfig.model_validate({
        "extraHeaders": {"X-Title": "my-fork", "X-Custom": "1"},
    })
    headers = _provider_extra_headers(spec, provider)

    assert headers["X-Title"] == "my-fork"
    assert headers["X-Custom"] == "1"
    assert headers["X-AIMLAPI-Partner-ID"] == "part_TcTxHfamJ2kkNiFsYzEVELTy"
    # The registry entry is a shared constant; building the per-request dict
    # must not write back into it.
    assert dict(spec.default_extra_headers) == before
