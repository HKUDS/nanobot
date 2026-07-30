from __future__ import annotations

import base64
import json
import queue
import socket
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from oauth_cli_kit.models import OAuthToken
from oauth_cli_kit.storage import FileTokenStorage

import nanobot.providers.openai_codex_oauth as codex_oauth
from nanobot.providers.openai_codex_oauth import (
    OpenAICodexOAuthError,
    OpenAICodexOAuthInputError,
    _build_authorization_url,
    _exchange_code,
    _generate_pkce,
    complete_openai_codex_oauth_login,
    start_openai_codex_oauth_login,
)


def _jwt(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


def test_authorization_url_matches_codex_pkce_contract() -> None:
    verifier, challenge = _generate_pkce()

    url = _build_authorization_url(
        codex_oauth.OPENAI_CODEX_PROVIDER,
        challenge=challenge,
        state="state-value",
    )

    params = parse_qs(urlsplit(url).query)
    assert len(verifier) >= 43
    assert params == {
        "response_type": ["code"],
        "client_id": [codex_oauth.OPENAI_CODEX_PROVIDER.client_id],
        "redirect_uri": ["http://localhost:1455/auth/callback"],
        "scope": ["openid profile email offline_access"],
        "code_challenge": [challenge],
        "code_challenge_method": ["S256"],
        "state": ["state-value"],
        "id_token_add_organizations": ["true"],
        "codex_cli_simplified_flow": ["true"],
        "originator": ["nanobot"],
    }


def test_remote_flow_requires_full_callback_url_and_persists_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(codex_oauth, "_make_callback_server", lambda _state, _queue: None)
    storage = FileTokenStorage(
        token_filename="codex.json",
        data_dir=tmp_path,
        import_codex_cli=False,
    )
    monkeypatch.setattr(codex_oauth, "_token_storage", lambda: storage)
    exchanged: dict[str, object] = {}

    def fake_exchange(code: str, *, verifier: str, proxy: str | None) -> OAuthToken:
        exchanged.update(code=code, verifier=verifier, proxy=proxy)
        return OAuthToken(
            access="access-token",
            refresh="refresh-token",
            expires=2_000_000_000_000,
            account_id="acct-test",
        )

    monkeypatch.setattr(codex_oauth, "_exchange_code", fake_exchange)
    flow = start_openai_codex_oauth_login(
        proxy="http://127.0.0.1:7890",
        timeout_s=5,
    )
    try:
        state = parse_qs(urlsplit(flow.authorization_url).query)["state"][0]
        with pytest.raises(OpenAICodexOAuthInputError, match="full callback URL"):
            complete_openai_codex_oauth_login(flow, "authorization-code")

        callback_url = (
            "http://localhost:1455/auth/callback?"
            + urlencode({"code": "authorization-code", "state": state})
        )
        token = complete_openai_codex_oauth_login(flow, callback_url)
    finally:
        flow.cancel()

    assert token is not None
    assert token.account_id == "acct-test"
    assert exchanged["code"] == "authorization-code"
    assert exchanged["verifier"]
    assert exchanged["proxy"] == "http://127.0.0.1:7890"
    assert storage.load() == token


def test_remote_flow_rejects_callback_with_wrong_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_oauth, "_make_callback_server", lambda _state, _queue: None)
    monkeypatch.setattr(
        codex_oauth,
        "_exchange_code",
        lambda *_args, **_kwargs: pytest.fail("token exchange must not run"),
    )
    flow = start_openai_codex_oauth_login(timeout_s=5)
    callback_url = (
        "http://localhost:1455/auth/callback?"
        + urlencode({"code": "authorization-code", "state": "wrong-state"})
    )
    try:
        with pytest.raises(OpenAICodexOAuthError, match="state did not match"):
            complete_openai_codex_oauth_login(flow, callback_url)
    finally:
        flow.cancel()


def test_local_callback_server_completes_flow_automatically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        callback_port = listener.getsockname()[1]
    monkeypatch.setattr(codex_oauth, "_CALLBACK_PORT", callback_port)

    result_queue: queue.Queue[codex_oauth._CallbackResult] = queue.Queue(maxsize=1)
    server = codex_oauth._make_callback_server("expected-state", result_queue)
    assert server is not None

    storage = FileTokenStorage(
        token_filename="codex.json",
        data_dir=tmp_path,
        import_codex_cli=False,
    )
    monkeypatch.setattr(codex_oauth, "_token_storage", lambda: storage)
    monkeypatch.setattr(
        codex_oauth,
        "_exchange_code",
        lambda code, *, verifier, proxy: OAuthToken(
            access=f"access-{code}",
            refresh=f"refresh-{verifier}",
            expires=2_000_000_000_000,
            account_id=proxy,
        ),
    )
    flow = codex_oauth.OpenAICodexOAuthLoginFlow(
        authorization_url="https://auth.openai.com/oauth/authorize",
        verifier="test-verifier",
        state="expected-state",
        proxy=None,
        result_queue=result_queue,
        server=server,
        timeout_s=5,
    )
    try:
        host = server.server_address[0]
        request_host = f"[{host}]" if ":" in host else host
        with httpx.Client(trust_env=False) as client:
            response = client.get(
                f"http://{request_host}:{callback_port}/auth/callback",
                params={"code": "local-code", "state": "expected-state"},
            )
        assert response.status_code == 200
        assert "Signed in to OpenAI Codex" in response.text
        assert "local-code" not in response.text

        token = None
        deadline = time.monotonic() + 2
        while token is None and time.monotonic() < deadline:
            token = complete_openai_codex_oauth_login(flow)
            if token is None:
                time.sleep(0.01)
    finally:
        flow.cancel()

    assert token is not None
    assert token.access == "access-local-code"
    assert storage.load() == token


def test_token_exchange_saves_account_identity_without_exposing_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = "acct-codex"
    access_token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account_id,
            }
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == codex_oauth.OPENAI_CODEX_PROVIDER.token_url
        form = parse_qs(request.content.decode())
        assert form["code"] == ["authorization-code"]
        assert form["code_verifier"] == ["verifier"]
        assert form["redirect_uri"] == ["http://localhost:1455/auth/callback"]
        return httpx.Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr(
        codex_oauth,
        "_http_client",
        lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    token = _exchange_code("authorization-code", verifier="verifier", proxy=None)

    assert token.access == access_token
    assert token.refresh == "refresh-token"
    assert token.account_id == account_id


def test_token_exchange_reports_bounded_upstream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "The authorization code has expired.",
            },
        )

    monkeypatch.setattr(
        codex_oauth,
        "_http_client",
        lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(
        OpenAICodexOAuthError,
        match=r"HTTP 400 \(invalid_grant: The authorization code has expired\.\)",
    ):
        _exchange_code("secret-code", verifier="secret-verifier", proxy=None)
