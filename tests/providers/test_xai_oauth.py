from __future__ import annotations

import json
import queue
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

import nanobot.providers.xai_oauth as xai_oauth
from nanobot.providers.xai_oauth import (
    XAI_CLIENT_ID,
    XAI_OAUTH_SCOPES,
    XAIOAuthError,
    XAIToken,
    _build_authorize_url,
    _CallbackResult,
    _Discovery,
    _generate_pkce,
    _make_callback_server,
    _validate_xai_endpoint,
    get_xai_oauth_login_status,
    get_xai_oauth_storage_path,
    get_xai_oauth_token,
    login_xai_oauth,
    logout_xai_oauth,
)


def _use_temp_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(xai_oauth, "get_data_dir", lambda: tmp_path)


def test_authorize_url_uses_pkce_and_frozen_xai_scope_contract() -> None:
    verifier, challenge = _generate_pkce()

    url = _build_authorize_url(
        "https://auth.x.ai/oauth2/authorize",
        redirect_uri="http://127.0.0.1:54321/callback",
        challenge=challenge,
        state="state-value",
        nonce="nonce-value",
    )

    params = parse_qs(urlsplit(url).query)
    assert len(verifier) >= 43
    assert params == {
        "response_type": ["code"],
        "client_id": [XAI_CLIENT_ID],
        "redirect_uri": ["http://127.0.0.1:54321/callback"],
        "scope": [" ".join(XAI_OAUTH_SCOPES)],
        "code_challenge": [challenge],
        "code_challenge_method": ["S256"],
        "state": ["state-value"],
        "nonce": ["nonce-value"],
        "referrer": ["nanobot"],
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://auth.x.ai/oauth2/token",
        "https://evil.example/oauth2/token",
        "https://auth.x.ai:444/oauth2/token",
        "https://user@auth.x.ai/oauth2/token",
        "https://auth.x.ai:invalid/oauth2/token",
    ],
)
def test_discovery_rejects_unsafe_endpoints(endpoint: str) -> None:
    with pytest.raises(XAIOAuthError, match="unsafe token endpoint"):
        _validate_xai_endpoint(endpoint, "token")


def test_callback_server_accepts_only_matching_state_and_allows_accounts_origin() -> None:
    results: queue.Queue[_CallbackResult] = queue.Queue(maxsize=1)
    server = _make_callback_server("expected-state", results)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = httpx.get(
            f"http://127.0.0.1:{server.server_port}/callback",
            params={"code": "one-time-code", "state": "expected-state"},
            headers={"Origin": "https://accounts.x.ai"},
        )
        result = results.get(timeout=1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://accounts.x.ai"
    assert response.headers["access-control-allow-private-network"] == "true"
    assert result == _CallbackResult(code="one-time-code", state="expected-state")
    assert "one-time-code" not in response.text


def test_login_uses_random_loopback_callback_and_saves_separate_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)
    discovery = _Discovery(
        authorization_endpoint="https://auth.x.ai/oauth2/authorize",
        token_endpoint="https://auth.x.ai/oauth2/token",
        userinfo_endpoint="https://auth.x.ai/oauth2/userinfo",
    )
    monkeypatch.setattr(xai_oauth, "_discover", lambda _proxy: discovery)
    exchanged: dict[str, str] = {}

    def fake_exchange(endpoint: str, **kwargs):
        exchanged.update(endpoint=endpoint, **kwargs)
        return {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
        }

    monkeypatch.setattr(xai_oauth, "_exchange_code", fake_exchange)
    monkeypatch.setattr(
        xai_oauth,
        "_fetch_account",
        lambda endpoint, access, proxy: "user@example.com",
    )
    opened_urls: list[str] = []

    def complete_in_browser(authorize_url: str) -> bool:
        opened_urls.append(authorize_url)
        params = parse_qs(urlsplit(authorize_url).query)
        callback_url = params["redirect_uri"][0]
        callback_query = urlencode({"code": "auth-code", "state": params["state"][0]})
        response = httpx.get(f"{callback_url}?{callback_query}")
        assert response.status_code == 200
        return True

    token = login_xai_oauth(
        print_fn=lambda _message: None,
        browser_opener=complete_in_browser,
        callback_timeout_s=1,
    )

    assert token.account_id == "user@example.com"
    assert exchanged["code"] == "auth-code"
    assert exchanged["redirect_uri"].startswith("http://127.0.0.1:")
    assert exchanged["verifier"]
    assert opened_urls
    assert get_xai_oauth_storage_path() == tmp_path / "auth" / "xai.json"
    saved = json.loads(get_xai_oauth_storage_path().read_text(encoding="utf-8"))
    assert saved["access"] == "access-secret"
    assert saved["refresh"] == "refresh-secret"
    assert get_xai_oauth_login_status() == token


def test_expired_token_refreshes_once_and_persists_rotated_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)
    expired = XAIToken(
        access="old-access",
        refresh="old-refresh",
        expires=int(time.time() * 1000) - 1,
        account_id="account",
    )
    xai_oauth._write_token(expired)
    calls: list[tuple[XAIToken, str | None]] = []

    def fake_refresh(token: XAIToken, proxy: str | None) -> XAIToken:
        calls.append((token, proxy))
        return XAIToken(
            access="new-access",
            refresh="new-refresh",
            expires=int(time.time() * 1000) + 3_600_000,
            account_id=token.account_id,
        )

    monkeypatch.setattr(xai_oauth, "_refresh_token", fake_refresh)

    refreshed = get_xai_oauth_token(proxy="http://127.0.0.1:7890")

    assert refreshed.access == "new-access"
    assert refreshed.refresh == "new-refresh"
    assert calls == [(expired, "http://127.0.0.1:7890")]
    assert get_xai_oauth_login_status() == refreshed


def test_missing_credentials_returns_actionable_login_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)

    with pytest.raises(XAIOAuthError, match="nanobot provider login xai-grok"):
        get_xai_oauth_token()


def test_logout_waits_for_inflight_refresh_and_removes_rotated_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)
    expired = XAIToken(
        access="old-access",
        refresh="old-refresh",
        expires=int(time.time() * 1000) - 1,
    )
    xai_oauth._write_token(expired)
    refresh_started = threading.Event()
    finish_refresh = threading.Event()
    logout_started = threading.Event()
    logout_finished = threading.Event()
    refresh_errors: list[Exception] = []
    logout_results: list[bool] = []

    def fake_refresh(token: XAIToken, _proxy: str | None) -> XAIToken:
        refresh_started.set()
        assert finish_refresh.wait(timeout=2)
        return XAIToken(
            access="new-access",
            refresh=token.refresh,
            expires=int(time.time() * 1000) + 3_600_000,
        )

    def refresh() -> None:
        try:
            get_xai_oauth_token()
        except Exception as exc:  # pragma: no cover - asserted below
            refresh_errors.append(exc)

    def logout() -> None:
        logout_started.set()
        logout_results.append(logout_xai_oauth())
        logout_finished.set()

    monkeypatch.setattr(xai_oauth, "_refresh_token", fake_refresh)
    refresh_thread = threading.Thread(target=refresh)
    refresh_thread.start()
    assert refresh_started.wait(timeout=2)

    logout_thread = threading.Thread(target=logout)
    logout_thread.start()
    assert logout_started.wait(timeout=2)
    assert not logout_finished.wait(timeout=0.05)
    finish_refresh.set()
    refresh_thread.join(timeout=2)
    logout_thread.join(timeout=2)

    assert not refresh_thread.is_alive()
    assert not logout_thread.is_alive()
    assert refresh_errors == []
    assert logout_results == [True]
    assert not get_xai_oauth_storage_path().exists()


def test_refresh_does_not_restore_credentials_removed_after_its_initial_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)
    expired = XAIToken(
        access="old-access",
        refresh="old-refresh",
        expires=int(time.time() * 1000) - 1,
    )
    xai_oauth._write_token(expired)
    real_load_token = xai_oauth._load_token
    initial_read_finished = threading.Event()
    continue_refresh = threading.Event()
    refresh_errors: list[Exception] = []
    first_load = True

    def gated_load_token() -> XAIToken | None:
        nonlocal first_load
        token = real_load_token()
        if first_load:
            first_load = False
            initial_read_finished.set()
            assert continue_refresh.wait(timeout=2)
        return token

    def refresh() -> None:
        try:
            get_xai_oauth_token()
        except Exception as exc:
            refresh_errors.append(exc)

    monkeypatch.setattr(xai_oauth, "_load_token", gated_load_token)
    refresh_thread = threading.Thread(target=refresh)
    refresh_thread.start()
    assert initial_read_finished.wait(timeout=2)

    assert logout_xai_oauth() is True
    continue_refresh.set()
    refresh_thread.join(timeout=2)

    assert not refresh_thread.is_alive()
    assert len(refresh_errors) == 1
    assert isinstance(refresh_errors[0], XAIOAuthError)
    assert "not signed in" in str(refresh_errors[0])
    assert not get_xai_oauth_storage_path().exists()
