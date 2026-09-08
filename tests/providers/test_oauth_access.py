"""Account checks use live catalog requests rather than cached fallback models."""

import importlib
from unittest.mock import Mock

import httpx
import pytest


@pytest.mark.parametrize("name", ["xai_grok", "openai_codex", "github_copilot"])
def test_account_access_calls_uncached_fetch_and_propagates_failure(monkeypatch, name):
    module = importlib.import_module(f"nanobot.providers.{name}_provider")
    fetch = Mock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr(module, f"_fetch_{name}_models", fetch)
    with pytest.raises(RuntimeError, match="unavailable"):
        getattr(module, f"check_{name}_access")("http://localhost:7890")
    fetch.assert_called_once_with("http://localhost:7890")


def test_grok_account_check_refreshes_rejected_access_token_once(monkeypatch):
    from nanobot.providers import xai_grok_provider as module

    rejected = httpx.HTTPStatusError("rejected", request=httpx.Request("GET", "https://example.test"),
                                     response=httpx.Response(401))
    fetch = Mock(side_effect=[rejected, ()])
    refresh = Mock()
    monkeypatch.setattr(module, "_fetch_xai_grok_models", fetch)
    monkeypatch.setattr(module, "get_xai_oauth_token", refresh)
    module.check_xai_grok_access()
    assert fetch.call_count == 2
    refresh.assert_called_once_with(proxy=None, force_refresh=True)


def test_grok_revoked_refresh_token_exposes_only_structured_category(monkeypatch):
    from nanobot.providers import xai_oauth
    from nanobot.providers.xai_oauth import XAIOAuthError

    response = httpx.Response(400, json={"error": "invalid_grant", "error_description": "secret"})
    error = xai_oauth._oauth_http_error(response, "token refresh")
    assert isinstance(error, XAIOAuthError)
    assert error.status_code == 400
    assert error.oauth_error == "invalid_grant"
