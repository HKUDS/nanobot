from __future__ import annotations

import pytest

from nanobot.config.schema import Config, ProviderConfig
from nanobot.providers.capabilities import FAST_MODE, NATIVE_SEARCH, resolve_provider_capability
from nanobot.providers.factory import provider_signature
from nanobot.providers.registry import find_by_name


def test_legacy_extra_body_capabilities_remain_enabled() -> None:
    codex = find_by_name("openai_codex")
    deepseek = find_by_name("deepseek")

    assert resolve_provider_capability(
        codex,
        ProviderConfig(extra_body={"service_tier": "priority"}),
        FAST_MODE,
    ) is True
    assert resolve_provider_capability(
        deepseek,
        ProviderConfig(extra_body={"tools": [{"type": "web_search"}]}),
        NATIVE_SEARCH,
    ) is True


def test_explicit_capability_switch_overrides_legacy_extra_body() -> None:
    codex = find_by_name("openai_codex")
    deepseek = find_by_name("deepseek")

    assert resolve_provider_capability(
        codex,
        ProviderConfig(
            extra_body={"service_tier": "priority"},
            capabilities={FAST_MODE: False},
        ),
        FAST_MODE,
    ) is False
    assert resolve_provider_capability(
        deepseek,
        ProviderConfig(
            extra_body={"tools": [{"type": "web_search"}]},
            capabilities={NATIVE_SEARCH: False},
        ),
        NATIVE_SEARCH,
    ) is False


@pytest.mark.parametrize("provider_name", ["deepseek", "xai_grok"])
def test_no_cost_native_search_defaults_enabled(provider_name: str) -> None:
    assert resolve_provider_capability(
        find_by_name(provider_name),
        ProviderConfig(),
        NATIVE_SEARCH,
    ) is True


@pytest.mark.parametrize(
    ("provider_name", "capability_name"),
    [("openai", NATIVE_SEARCH), ("openai_codex", FAST_MODE)],
)
def test_cost_affecting_capabilities_remain_opt_in(
    provider_name: str,
    capability_name: str,
) -> None:
    assert resolve_provider_capability(
        find_by_name(provider_name),
        ProviderConfig(),
        capability_name,
    ) is False


def test_config_rejects_capabilities_not_declared_by_provider() -> None:
    with pytest.raises(ValueError, match="providers.deepseek.capabilities.fast_mode"):
        Config.model_validate({
            "providers": {"deepseek": {"capabilities": {"fast_mode": True}}}
        })

    with pytest.raises(ValueError, match="providers.openai.capabilities.fast_mode"):
        Config.model_validate({
            "providers": {"openai": {"capabilities": {"fast_mode": True}}}
        })


def test_openai_native_search_rejects_chat_completions_api_type() -> None:
    with pytest.raises(ValueError, match="native_search requires"):
        Config.model_validate({
            "providers": {
                "openai": {
                    "apiType": "chat_completions",
                    "capabilities": {"native_search": True},
                }
            }
        })


def test_provider_signature_tracks_capability_changes() -> None:
    model_selection = {
        "agents": {"defaults": {"modelPreset": "search"}},
        "modelPresets": {
            "search": {"model": "deepseek-v4-flash", "provider": "deepseek"}
        },
    }
    disabled = Config.model_validate({
        **model_selection,
        "providers": {"deepseek": {"capabilities": {NATIVE_SEARCH: False}}},
    })
    enabled = Config.model_validate({
        **model_selection,
        "providers": {"deepseek": {"capabilities": {NATIVE_SEARCH: True}}},
    })

    assert provider_signature(disabled) != provider_signature(enabled)
