from __future__ import annotations

import json
import os
import stat
from urllib.parse import parse_qs, urlparse

import pytest

import nanobot.providers.xai_oauth_provider as auth


def test_build_xai_authorization_url_includes_pkce_and_grok_scope() -> None:
    endpoints = auth.XaiOAuthEndpoints(
        authorization_endpoint="https://auth.x.ai/authorize",
        token_endpoint="https://auth.x.ai/oauth/token",
    )

    url = auth.build_xai_authorization_url(
        endpoints,
        verifier="verifier",
        state="state",
        nonce="nonce",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.hostname == "auth.x.ai"
    assert params["client_id"] == [auth.DEFAULT_XAI_CLIENT_ID]
    assert params["code_challenge"] == [auth.pkce_challenge("verifier")]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == [auth.DEFAULT_XAI_SCOPE]
    assert params["nonce"] == ["nonce"]
    assert params["plan"] == ["generic"]
    assert params["referrer"] == ["nanobot"]


def test_parse_callback_value_accepts_fallback_shapes() -> None:
    assert auth._parse_callback_value("https://localhost/callback?code=abc&state=state") == ("abc", "state")
    assert auth._parse_callback_value("?code=abc&state=state") == ("abc", "state")
    assert auth._parse_callback_value("code=abc&state=state") == ("abc", "state")
    assert auth._parse_callback_value("fallback-code") == ("fallback-code", None)


def test_file_storage_fallback_is_private_and_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "_keyring_set", lambda _tokens: False)
    monkeypatch.setattr(auth, "_keyring_get", lambda: None)

    saved = auth.save_xai_oauth_credential(
        auth.XaiOAuthCredential(
            access_token="access",
            refresh_token="refresh",
            expires_at=123.0,
            account_id="acct",
        )
    )

    path = auth.get_xai_oauth_metadata_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert saved.storage == "file"
    assert payload["storage"] == "file"
    assert payload["tokens"]["access_token"] == "access"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    loaded = auth.load_xai_oauth_credential()
    assert loaded is not None
    assert loaded.access_token == "access"
    assert loaded.refresh_token == "refresh"
    assert loaded.account_id == "acct"
    assert loaded.storage == "file"


def test_keyring_storage_keeps_tokens_out_of_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path))
    secret: dict[str, object] = {}

    def fake_set(tokens: dict[str, object]) -> bool:
        secret.update(tokens)
        return True

    monkeypatch.setattr(auth, "_keyring_set", fake_set)
    monkeypatch.setattr(auth, "_keyring_get", lambda: dict(secret))

    auth.save_xai_oauth_credential(
        auth.XaiOAuthCredential(
            access_token="access",
            refresh_token="refresh",
            expires_at=123.0,
            account_id="acct",
        )
    )

    payload = json.loads(auth.get_xai_oauth_metadata_path().read_text(encoding="utf-8"))
    assert payload["storage"] == "keyring"
    assert "tokens" not in payload
    assert auth.load_xai_oauth_credential().access_token == "access"


def test_exchange_xai_oauth_code_sends_required_code_challenge(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def post(self, url: str, headers: dict[str, str], data: dict[str, str]) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setattr(auth.httpx, "Client", FakeClient)
    endpoints = auth.XaiOAuthEndpoints(
        authorization_endpoint="https://auth.x.ai/authorize",
        token_endpoint="https://auth.x.ai/oauth/token",
    )

    credential = auth.exchange_xai_oauth_code("code", verifier="verifier", endpoints=endpoints)

    assert credential.access_token == "access"
    assert captured["url"] == "https://auth.x.ai/oauth/token"
    data = captured["data"]
    assert data["code_verifier"] == "verifier"
    assert data["code_challenge"] == auth.pkce_challenge("verifier")
    assert data["code_challenge_method"] == "S256"


def test_rejects_non_xai_discovery_endpoints() -> None:
    with pytest.raises(RuntimeError):
        auth._validate_xai_endpoint("https://example.com/oauth/token", "token_endpoint")
