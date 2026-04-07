"""Tests for the public provider plugin surface."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.plugins.providers import (
    ProviderSpec,
    apply_generation_defaults,
    create_provider,
    discover_provider_plugins,
    get_provider_factory,
    get_provider_specs,
    normalize_provider_name,
    register_provider_factory,
    register_provider_spec,
    unregister_provider_factory,
    unregister_provider_spec,
)
import nanobot.providers.registry as provider_registry


@pytest.fixture(autouse=True)
def _reset_provider_plugin_state():
    original_providers = provider_registry.PROVIDERS
    original_factories = dict(provider_registry._RUNTIME_PROVIDER_FACTORIES)
    original_discovered = provider_registry._PLUGINS_DISCOVERED

    provider_registry.PROVIDERS = tuple(
        spec for spec in original_providers if spec.name in provider_registry._BUILTIN_PROVIDER_NAMES
    )
    provider_registry._RUNTIME_PROVIDER_FACTORIES.clear()
    provider_registry._PLUGINS_DISCOVERED = True
    yield
    provider_registry.PROVIDERS = original_providers
    provider_registry._RUNTIME_PROVIDER_FACTORIES.clear()
    provider_registry._RUNTIME_PROVIDER_FACTORIES.update(original_factories)
    provider_registry._PLUGINS_DISCOVERED = original_discovered


def _demo_spec() -> ProviderSpec:
    return ProviderSpec(
        name="demo-cloud",
        keywords=("demo-cloud", "demo"),
        env_key="DEMO_CLOUD_API_KEY",
        display_name="Demo Cloud",
        backend="openai_compat",
        default_api_base="https://demo.example/v1",
    )


def _demo_config() -> Config:
    return Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "demoCloud",
                    "model": "demo-cloud/chat-pro",
                    "temperature": 0.33,
                    "maxTokens": 1024,
                }
            },
            "providers": {
                "demoCloud": {
                    "apiKey": "plugin-key",
                    "apiBase": "https://demo.example/v1",
                    "extraHeaders": {"X-Tenant": "team-a"},
                    "region": "cn-hz",
                }
            },
        }
    )


def _make_entry_point(name: str, value):
    return SimpleNamespace(name=name, load=lambda _value=value: _value)


def test_normalize_provider_name_handles_hyphen_and_camel_case():
    assert normalize_provider_name("demo-cloud") == "demo_cloud"
    assert normalize_provider_name("demoCloud") == "demo_cloud"


def test_providers_config_accepts_plugin_sections_and_extra_fields():
    cfg = ProvidersConfig.model_validate(
        {
            "demoCloud": {
                "apiKey": "plugin-key",
                "region": "cn-hz",
            }
        }
    )

    section = getattr(cfg, "demo_cloud", None)
    assert isinstance(section, dict)
    assert section["apiKey"] == "plugin-key"
    assert section["region"] == "cn-hz"


def test_register_and_unregister_provider_spec_normalizes_name():
    spec = register_provider_spec(_demo_spec())

    assert spec.name == "demo_cloud"
    assert any(item.name == "demo_cloud" for item in get_provider_specs())

    unregister_provider_spec("demo-cloud")
    assert all(item.name != "demo_cloud" for item in get_provider_specs())


def test_register_and_unregister_provider_factory_normalizes_name():
    factory = MagicMock()

    register_provider_factory("demo-cloud", factory)
    assert get_provider_factory("demoCloud") is factory

    unregister_provider_factory("demo_cloud")
    assert get_provider_factory("demo-cloud") is None


def test_discover_provider_plugins_loads_specs_and_factories():
    spec = _demo_spec()
    factory = MagicMock()

    def _fake_entry_points(*, group: str):
        if group == "nanobot.provider_specs":
            return [_make_entry_point("demo-cloud", spec)]
        if group == "nanobot.providers":
            return [_make_entry_point("demo-cloud", factory)]
        return []

    provider_registry._PLUGINS_DISCOVERED = False
    with patch("nanobot.providers.registry.entry_points", side_effect=_fake_entry_points):
        discover_provider_plugins(force=True)

    assert any(item.name == "demo_cloud" for item in get_provider_specs())
    assert get_provider_factory("demo_cloud") is factory


def test_discover_provider_plugins_ignores_broken_entry_point():
    def _boom():
        raise RuntimeError("broken")

    provider_registry._PLUGINS_DISCOVERED = False
    with patch(
        "nanobot.providers.registry.entry_points",
        side_effect=lambda *, group: [SimpleNamespace(name="broken", load=_boom)] if group == "nanobot.providers" else [],
    ):
        discover_provider_plugins(force=True)

    assert get_provider_factory("broken") is None


def test_apply_generation_defaults_sets_provider_generation():
    provider = SimpleNamespace(generation=None)
    defaults = SimpleNamespace(temperature=0.2, max_tokens=2048, reasoning_effort="medium")

    apply_generation_defaults(provider, defaults)

    assert provider.generation.temperature == 0.2
    assert provider.generation.max_tokens == 2048
    assert provider.generation.reasoning_effort == "medium"


def test_create_provider_uses_plugin_factory_and_applies_defaults():
    config = _demo_config()
    register_provider_spec(_demo_spec())
    plugin_provider = SimpleNamespace(generation=None)
    factory = MagicMock(return_value=plugin_provider)
    register_provider_factory("demo-cloud", factory)
    native_factory = MagicMock(return_value="native")

    result = create_provider(config, native_factory=native_factory)

    assert result is plugin_provider
    assert plugin_provider.generation.temperature == 0.33
    assert plugin_provider.generation.max_tokens == 1024
    native_factory.assert_not_called()
    factory.assert_called_once()
    factory_kwargs = factory.call_args.kwargs
    assert factory_kwargs["model"] == "demo-cloud/chat-pro"
    assert factory_kwargs["spec"].name == "demo_cloud"
    assert factory_kwargs["config"]["region"] == "cn-hz"


def test_create_provider_falls_back_to_native_factory_on_plugin_error():
    config = _demo_config()
    register_provider_spec(_demo_spec())
    register_provider_factory("demo-cloud", MagicMock(side_effect=RuntimeError("boom")))
    native_factory = MagicMock(return_value="native")

    result = create_provider(config, native_factory=native_factory)

    assert result == "native"
    native_factory.assert_called_once_with(config)


def test_sdk_make_provider_uses_registered_plugin_factory():
    from nanobot.nanobot import _make_provider

    config = _demo_config()
    register_provider_spec(_demo_spec())
    plugin_provider = SimpleNamespace(generation=None)
    register_provider_factory("demo-cloud", MagicMock(return_value=plugin_provider))

    result = _make_provider(config)

    assert result is plugin_provider
    assert result.generation.temperature == 0.33


def test_cli_make_provider_uses_registered_plugin_factory():
    from nanobot.cli.commands import _make_provider

    config = _demo_config()
    register_provider_spec(_demo_spec())
    plugin_provider = SimpleNamespace(generation=None)
    register_provider_factory("demo-cloud", MagicMock(return_value=plugin_provider))

    result = _make_provider(config)

    assert result is plugin_provider
    assert result.generation.max_tokens == 1024