from __future__ import annotations

from typing import Any

import pytest

from nanobot.config.schema import Config
from nanobot.webui.settings_models import (
    WebUISettingsError,
    create_model_configuration,
    model_settings_payload,
    provider_models_payload,
    update_agent_model_settings,
    update_model_configuration,
    update_provider_settings,
)


def test_preset_request_overrides_redact_roundtrip_and_clear():
    config = Config()
    config.providers.openai.api_key = "fixture"
    name = create_model_configuration(config, {
        "name": ["custom"], "provider": ["openai"], "model": ["gpt-4o"],
        "extra_headers": ['{"Authorization":"private-value","X-Route":"one"}'],
        "extra_body": ['{"metadata":{"api_key":"private-body","route":"one"}}'],
    }, oauth_status=_oauth_status)
    payload = model_settings_payload(config, oauth_status=_oauth_status)
    row = next(row for row in payload["model_presets"] if row["name"] == name)
    assert row["extra_headers"]["Authorization"] == "••••••••"
    assert row["extra_body"]["metadata"]["api_key"] == "••••••••"
    assert "private-value" not in str(payload)
    assert "private-body" not in str(payload)
    assert update_model_configuration(config, {
        "name": [name], "extraHeaders": ['{"Authorization":"••••••••","X-Route":"two"}'],
    }, oauth_status=_oauth_status)
    assert config.model_presets[name].extra_headers == {"Authorization": "private-value", "X-Route": "two"}
    assert update_model_configuration(config, {
        "name": [name], "extra_headers": [""], "extra_body": ["{}"],
    }, oauth_status=_oauth_status)
    assert config.model_presets[name].extra_headers is None
    assert config.model_presets[name].extra_body is None
    with pytest.raises(WebUISettingsError, match="JSON object"):
        update_model_configuration(config, {"name": [name], "extra_query": ["[]"]}, oauth_status=_oauth_status)
    assert config.model_presets[name].extra_query is None


def test_preset_provider_switch_clears_secrets():
    config = Config()
    config.providers.openai.api_key = "fixture"
    config.providers.anthropic.api_key = "fixture"
    name = create_model_configuration(config, {
        "name": ["custom"], "provider": ["openai"], "model": ["gpt-4o"],
        "extra_headers": ['{"Authorization":"private-value"}'],
    }, oauth_status=_oauth_status)
    update_model_configuration(config, {
        "name": [name], "provider": ["anthropic"], "model": ["claude-sonnet-4-6"],
    }, oauth_status=_oauth_status)
    assert config.model_presets[name].extra_headers is None


def _oauth_status(_spec: Any) -> dict[str, Any]:
    return {
        "configured": False,
        "account": None,
        "expires_at": None,
        "login_supported": True,
    }


@pytest.mark.parametrize("target", ["tenant_a", "tenant_b"])
@pytest.mark.parametrize("environment_model", [False, True])
def test_auto_preset_model_change_isolates_connection_settings(target, environment_model, monkeypatch):
    monkeypatch.setenv("NANOBOT_TEST_MODEL", "tenant_a/old")
    config = Config.model_validate({
        "providers": {name: {"apiKey": "fixture", "apiBase": "https://shared.test/v1"}
                      for name in ("tenant_b", "tenant_a")},
        "modelPresets": {"primary": {
            "provider": "auto", "model": "${NANOBOT_TEST_MODEL}" if environment_model else "tenant_a/old",
            "extraHeaders": {"X-Token": "private"},
            "extraQuery": {"key": "private"}, "extraBody": {"token": "private"},
        }},
    })
    if environment_model:
        update_model_configuration(config, {
            "name": ["primary"], "temperature": ["0.3"],
        }, oauth_status=_oauth_status)
        assert config.model_presets["primary"].model == "${NANOBOT_TEST_MODEL}"
    update_model_configuration(config, {
        "name": ["primary"], "model": [f"{target}/new"],
    }, oauth_status=_oauth_status)
    preset = config.model_presets["primary"]
    expected = "private" if target == "tenant_a" else None
    assert (preset.extra_headers or {}).get("X-Token") == expected
    assert (preset.extra_query or {}).get("key") == expected
    assert (preset.extra_body or {}).get("token") == expected


def test_auto_routing_retains_same_connection_settings_but_new_connection_accepts_only_new_values():
    config = Config.model_validate({
        "providers": {name: {"apiKey": "fixture", "apiBase": "https://shared.test/v1"}
                      for name in ("tenant_a", "tenant_b")},
        "modelPresets": {"primary": {
            "provider": "tenant_a", "model": "old", "extraHeaders": {"X-Token": "private"},
        }},
    })
    update_model_configuration(config, {
        "name": ["primary"], "provider": ["auto"], "model": ["tenant_a/new"],
    }, oauth_status=_oauth_status)
    assert config.model_presets["primary"].extra_headers == {"X-Token": "private"}
    # A stale form must not restore the old connection's redacted credential.
    with pytest.raises(WebUISettingsError):
        update_model_configuration(config.model_copy(deep=True), {
            "name": ["primary"], "provider": ["tenant_b"],
            "extra_headers": ['{"X-Token":"••••••••"}'],
        }, oauth_status=_oauth_status)
    update_model_configuration(config, {
        "name": ["primary"], "provider": ["tenant_b"],
        "extra_headers": ['{"X-Token":"new-secret"}'],
    }, oauth_status=_oauth_status)
    assert config.model_presets["primary"].extra_headers == {"X-Token": "new-secret"}


def test_model_domain_owns_dto_and_config_updates() -> None:
    config = Config()
    config.providers.openrouter.api_key = "sk-before"

    agent_changed = update_agent_model_settings(
        config,
        {
            "model": ["openai/gpt-5.4"],
            "provider": ["openrouter"],
            "context_window_tokens": ["200000"],
        },
        oauth_status=_oauth_status,
    )
    provider_changed, restart_required = update_provider_settings(
        config,
        {
            "provider": ["openrouter"],
            "api_key": ["sk-after"],
        },
    )
    payload = model_settings_payload(config, oauth_status=_oauth_status)

    assert agent_changed is True
    assert provider_changed is True
    assert restart_required is False
    assert config.agents.defaults.model == "openai/gpt-5.4"
    assert config.agents.defaults.provider == "openrouter"
    assert config.agents.defaults.context_window_tokens == 200_000
    assert config.providers.openrouter.api_key == "sk-after"
    assert set(payload) == {
        "agent",
        "model_presets",
        "model_call_order",
        "model_call_order_editable",
        "model_configuration_migratable",
        "model_api_resolution_supported",
        "provider_api_configuration_supported",
        "model_request_overrides_supported",
        "providers",
    }
    assert payload["agent"]["model"] == "openai/gpt-5.4"
    assert payload["model_api_resolution_supported"] is True


@pytest.mark.parametrize("tokens", [128_000, 131_072, 1_000_000])
def test_default_context_window_accepts_custom_tokens(tokens: int) -> None:
    config = Config()
    assert update_agent_model_settings(
        config, {"context_window_tokens": [str(tokens)]}, oauth_status=_oauth_status,
    )
    assert config.agents.defaults.context_window_tokens == tokens
    assert model_settings_payload(config, oauth_status=_oauth_status)["agent"]["context_window_tokens"] == tokens


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "abc"])
def test_default_context_window_rejects_invalid_tokens(value: str) -> None:
    config = Config()
    with pytest.raises(WebUISettingsError, match="context_window_tokens must"):
        update_agent_model_settings(
            config, {"context_window_tokens": [value]}, oauth_status=_oauth_status,
        )
    assert config.agents.defaults.context_window_tokens == 200_000


@pytest.mark.parametrize("provider", ["openai_codex", "xai_grok", "github_copilot"])
@pytest.mark.parametrize("refresh", [False, True])
def test_provider_model_refresh_reaches_oauth_catalog(monkeypatch, provider, refresh):
    from unittest.mock import Mock

    from nanobot.providers.oauth_model_catalog import OAuthModelCatalogSnapshot

    catalog = Mock(return_value=OAuthModelCatalogSnapshot(models=(), source="remote", fetched_at=123))
    monkeypatch.setattr("nanobot.webui.settings_models.get_oauth_model_catalog", catalog)
    query = {"provider": [provider]}
    if refresh:
        query["refresh"] = ["1"]

    config = Config.model_validate({"providers": {provider: {}}})
    provider_models_payload(config, query, http_get=Mock())

    catalog.assert_called_once_with(provider, proxy=None, refresh=refresh)
