from __future__ import annotations

import json
import time
from typing import Any

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ProviderConfig
from nanobot.webui.settings_models import (
    WebUISettingsError,
    model_settings_payload,
    oauth_provider_status,
    provider_models_payload,
    remove_provider_settings,
    update_agent_model_settings,
    update_provider_settings,
)


@pytest.mark.parametrize("provider_name", [
    "openai", "tenant", "openai_codex", "xai_grok", "github_copilot",
])
def test_provider_removal_persists_without_removing_oauth_credentials(tmp_path, monkeypatch, provider_name):
    from oauth_cli_kit.models import OAuthToken
    from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
    from oauth_cli_kit.storage import FileTokenStorage

    path = tmp_path / "config.json"
    monkeypatch.setattr(FileTokenStorage, "get_token_path", lambda self: tmp_path / self._token_filename)
    monkeypatch.setattr("oauth_cli_kit.storage._try_import_codex_cli_token", lambda _path: None)
    xai_credentials = tmp_path / "xai.json"
    monkeypatch.setattr("nanobot.providers.xai_oauth.get_xai_oauth_storage_path", lambda: xai_credentials)
    token = OAuthToken(access="saved-token", refresh="saved-refresh", expires=int(time.time() * 1000) + 60_000)
    credentials = None
    if provider_name in {"openai_codex", "github_copilot"}:
        filename = OPENAI_CODEX_PROVIDER.token_filename if provider_name == "openai_codex" else "github-copilot.json"
        storage = FileTokenStorage(token_filename=filename, import_codex_cli=False)
        storage.save(token)
        credentials = storage.get_token_path()
    elif provider_name == "xai_grok":
        xai_credentials.write_text(json.dumps({"access": token.access, "refresh": token.refresh, "expires": token.expires}), encoding="utf-8")
        credentials = xai_credentials
    credential_bytes = credentials.read_bytes() if credentials else None
    config = Config.model_validate({"providers": {provider_name: {}}})
    save_config(config, path)

    before = model_settings_payload(load_config(path), oauth_status=oauth_provider_status)
    before_row = next(row for row in before["providers"] if row["name"] == provider_name)
    assert before_row["has_config"] is True
    remove_provider_settings(config, {"provider": [provider_name]})
    save_config(config, path)
    reloaded = load_config(path)
    assert getattr(reloaded.providers, provider_name, None) is None
    if credentials:
        assert credentials.read_bytes() == credential_bytes
    persisted = json.loads(path.read_text(encoding="utf-8"))["providers"]
    assert not persisted

    if provider_name in {"openai_codex", "xai_grok", "github_copilot"}:
        row = next(row for row in model_settings_payload(reloaded, oauth_status=oauth_provider_status)["providers"]
                   if row["name"] == provider_name)
        assert row["oauth_authenticated"] is True
        assert row["has_config"] is False
        assert row["configured"] is False
        def http_get(*args, **kwargs):
            raise AssertionError("A removed provider must not fetch its model catalog")

        catalog = provider_models_payload(reloaded, {"provider": [provider_name]}, http_get=http_get)
        assert catalog["status"] == "not_configured"
        update_provider_settings(reloaded, {"provider": [provider_name]})
        save_config(reloaded, path)
        alias = {"openai_codex": "openaiCodex", "xai_grok": "xaiGrok", "github_copilot": "githubCopilot"}[provider_name]
        assert json.loads(path.read_text(encoding="utf-8"))["providers"] == {alias: {}}
        row = next(row for row in model_settings_payload(load_config(path), oauth_status=oauth_provider_status)["providers"]
                   if row["name"] == provider_name)
        assert row["has_config"] is True
        assert row["configured"] is True


def _oauth_status(_spec: Any) -> dict[str, Any]:
    return {
        "configured": False,
        "account": None,
        "expires_at": None,
        "login_supported": True,
    }


def test_model_domain_owns_dto_and_config_updates() -> None:
    config = Config()
    config.providers.openrouter = ProviderConfig(api_key="sk-before")

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
