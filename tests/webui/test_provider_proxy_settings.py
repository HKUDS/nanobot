from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ProviderConfig
from nanobot.providers.registry import PROVIDERS
from nanobot.webui import settings_models
from nanobot.webui.settings_services import WebUIOAuthFlowRegistry

PROXY = "http://127.0.0.1:7890"


@pytest.mark.parametrize("spec", PROVIDERS, ids=lambda spec: spec.name)
def test_every_provider_advertises_saves_and_clears_proxy(spec, tmp_path):
    config = Config()
    def oauth_status(_):
        return {
            "configured": False,
            "account": None,
            "expires_at": None,
            "login_supported": True,
        }
    row = settings_models._provider_settings_row(
        spec.name, spec, getattr(config.providers, spec.name), oauth_status,
    )
    assert row["advanced_fields"].count("proxy") == 1
    changed, _ = settings_models.update_provider_settings(
        config, {"provider": [spec.name], "proxy": [f" {PROXY} "]},
    )
    assert changed
    assert getattr(config.providers, spec.name).proxy == PROXY
    path = tmp_path / "config.json"
    save_config(config, path)
    assert getattr(load_config(path).providers, spec.name).proxy == PROXY
    changed, _ = settings_models.update_provider_settings(
        config, {"provider": [spec.name], "proxy": ["  "]},
    )
    assert changed
    assert getattr(config.providers, spec.name).proxy is None
    save_config(config, path)
    assert getattr(load_config(path).providers, spec.name).proxy is None


def test_custom_provider_advertises_saves_and_clears_proxy():
    config = Config()
    name = settings_models.create_provider_settings(
        config, {"name": ["Example"], "apiBase": ["https://example.test/v1"]},
    )
    spec, _, _ = settings_models.resolve_settings_provider(config, name)
    assert "proxy" in settings_models._provider_advanced_field_names(name, spec)
    settings_models.update_provider_settings(config, {"provider": [name], "proxy": [PROXY]})
    assert getattr(config.providers, name).proxy == PROXY
    settings_models.update_provider_settings(config, {"provider": [name], "proxy": [""]})
    assert getattr(config.providers, name).proxy is None


@pytest.mark.parametrize("field", ["apiKey", "apiBase", "extraBody"])
def test_copilot_credentials_and_unsupported_fields_remain_read_only(field):
    with pytest.raises(settings_models.WebUISettingsError, match="only supports proxy settings"):
        settings_models.update_provider_settings(
            Config(), {"provider": ["github_copilot"], field: ["{}"]},
        )


def test_copilot_login_resolves_and_passes_proxy(monkeypatch):
    constructor = Mock(return_value=SimpleNamespace(
        start=Mock(), authorization_url="https://github.com/login/device",
        user_code="ABCD", remaining_seconds=60,
    ))
    monkeypatch.setattr(
        "nanobot.providers.github_copilot_oauth.GitHubCopilotOAuthFlow", constructor,
    )
    monkeypatch.setenv("COPILOT_TEST_PROXY", PROXY)
    config = Config()
    config.providers.github_copilot.proxy = "${COPILOT_TEST_PROXY}"
    flows = WebUIOAuthFlowRegistry()
    result = settings_models.login_oauth_provider(
        config, {"provider": ["github_copilot"]}, oauth_flows=flows,
        config_path=None, settings_payload=lambda **_: {},
    )
    assert result["status"] == "authorization_required"
    constructor.assert_called_once_with(proxy=PROXY)
    constructor.return_value.start.assert_called_once()


@pytest.mark.parametrize("proxy", [None, "${CATALOG_TEST_PROXY}"])
def test_model_catalog_uses_provider_proxy_without_changing_default(monkeypatch, proxy):
    monkeypatch.setenv("CATALOG_TEST_PROXY", PROXY)
    config = Config()
    config.providers.deepseek = ProviderConfig(api_key="key", proxy=proxy)
    get = Mock(return_value=httpx.Response(
        200, json={"data": [{"id": "deepseek-chat"}]},
        request=httpx.Request("GET", "https://api.deepseek.com/models"),
    ))
    result = settings_models.provider_models_payload(
        config, {"provider": ["deepseek"]}, http_get=get,
    )
    assert result["status"] == "available"
    kwargs = get.call_args.kwargs
    if proxy:
        assert kwargs["proxy"] == PROXY
        assert kwargs["trust_env"] is False
    else:
        assert "proxy" not in kwargs
        assert "trust_env" not in kwargs
