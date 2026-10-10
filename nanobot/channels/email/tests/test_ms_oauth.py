from __future__ import annotations

import queue
import threading
import time
import urllib.request

import pytest

import nanobot.channels.email.ms_oauth as ms_oauth
from nanobot.channels.email.ms_oauth import (
    MicrosoftOAuthError,
    MSOAuthToken,
    account_fingerprint,
    get_email_oauth_login_status,
    get_email_oauth_token,
    logout_email_oauth,
)


def _use_temp_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(ms_oauth, "get_data_dir", lambda: tmp_path)


def _write_token(monkeypatch: pytest.MonkeyPatch, tmp_path, **overrides) -> MSOAuthToken:
    _use_temp_credentials(monkeypatch, tmp_path)
    fields = dict(
        access="access-1",
        refresh="refresh-1",
        expires=int(time.time() * 1000) + 60 * 60 * 1000,
        scope="offline_access IMAP.AccessAsUser.All SMTP.Send",
        fingerprint=account_fingerprint("tenant-1", "client-1", "bot@example.com"),
    )
    fields.update(overrides)
    token = MSOAuthToken(**fields)
    ms_oauth._write_token(token)  # noqa: SLF001
    return token


def test_account_fingerprint_is_stable_and_discriminates_inputs() -> None:
    a = account_fingerprint("tenant-1", "client-1", "Bot@Example.com")
    b = account_fingerprint("tenant-1", "client-1", "bot@example.com")
    c = account_fingerprint("tenant-2", "client-1", "bot@example.com")
    assert a == b  # case-insensitive mailbox
    assert a != c


def test_get_login_status_returns_none_when_no_token(monkeypatch, tmp_path) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)
    assert get_email_oauth_login_status("tenant-1", "client-1", "bot@example.com") is None


def test_get_login_status_returns_none_on_fingerprint_mismatch(monkeypatch, tmp_path) -> None:
    _write_token(monkeypatch, tmp_path)
    assert get_email_oauth_login_status("tenant-1", "client-1", "someone-else@example.com") is None


def test_get_login_status_returns_token_on_match(monkeypatch, tmp_path) -> None:
    token = _write_token(monkeypatch, tmp_path)
    status = get_email_oauth_login_status("tenant-1", "client-1", "bot@example.com")
    assert status == token


def test_get_token_raises_when_not_signed_in(monkeypatch, tmp_path) -> None:
    _use_temp_credentials(monkeypatch, tmp_path)
    with pytest.raises(MicrosoftOAuthError, match="not signed in"):
        get_email_oauth_token(
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            mailbox="bot@example.com",
        )


def test_get_token_returns_fresh_token_without_refresh(monkeypatch, tmp_path) -> None:
    token = _write_token(monkeypatch, tmp_path)

    def fail_refresh(*_a, **_kw):
        raise AssertionError("should not refresh a fresh token")

    monkeypatch.setattr(ms_oauth, "_refresh_token", fail_refresh)

    result = get_email_oauth_token(
        tenant_id="tenant-1",
        client_id="client-1",
        client_secret="secret-1",
        mailbox="bot@example.com",
    )
    assert result == token


def test_get_token_refreshes_stale_token_and_persists_it(monkeypatch, tmp_path) -> None:
    _write_token(monkeypatch, tmp_path, expires=int(time.time() * 1000) - 1000)

    refreshed = MSOAuthToken(
        access="access-2",
        refresh="refresh-2",
        expires=int(time.time() * 1000) + 60 * 60 * 1000,
        scope="offline_access IMAP.AccessAsUser.All SMTP.Send",
        fingerprint=account_fingerprint("tenant-1", "client-1", "bot@example.com"),
    )
    calls: list[str] = []

    def fake_refresh(token, **kwargs):
        calls.append(token.access)
        return refreshed

    monkeypatch.setattr(ms_oauth, "_refresh_token", fake_refresh)

    result = get_email_oauth_token(
        tenant_id="tenant-1",
        client_id="client-1",
        client_secret="secret-1",
        mailbox="bot@example.com",
    )
    assert result == refreshed
    assert calls == ["access-1"]
    assert get_email_oauth_login_status("tenant-1", "client-1", "bot@example.com") == refreshed


def test_get_token_without_refresh_token_raises(monkeypatch, tmp_path) -> None:
    _write_token(monkeypatch, tmp_path, expires=int(time.time() * 1000) - 1000, refresh=None)

    with pytest.raises(MicrosoftOAuthError, match="expired"):
        get_email_oauth_token(
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            mailbox="bot@example.com",
        )


def test_logout_removes_token_file(monkeypatch, tmp_path) -> None:
    _write_token(monkeypatch, tmp_path)
    assert logout_email_oauth() is True
    assert get_email_oauth_login_status("tenant-1", "client-1", "bot@example.com") is None
    assert logout_email_oauth() is False


def test_exchange_callback_rejects_response_with_no_state() -> None:
    """A bare pasted authorization code carries no state and must be
    rejected — without PKCE, state is the only defense against exchanging a
    code that belongs to an unrelated authorization flow."""
    callback = ms_oauth._CallbackResult(code="some-code", state=None)  # noqa: SLF001
    with pytest.raises(MicrosoftOAuthError, match="could not be verified"):
        ms_oauth._exchange_callback(  # noqa: SLF001
            callback,
            expected_state="expected-state",
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            mailbox="bot@example.com",
        )


def test_exchange_callback_rejects_mismatched_state() -> None:
    callback = ms_oauth._CallbackResult(code="some-code", state="wrong-state")  # noqa: SLF001
    with pytest.raises(MicrosoftOAuthError, match="could not be verified"):
        ms_oauth._exchange_callback(  # noqa: SLF001
            callback,
            expected_state="expected-state",
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            mailbox="bot@example.com",
        )


def test_start_email_oauth_login_wraps_port_bind_failure(monkeypatch) -> None:
    def _fail_bind(*_args, **_kwargs):
        raise OSError("Address already in use")

    monkeypatch.setattr(ms_oauth, "_make_callback_servers", _fail_bind)

    with pytest.raises(MicrosoftOAuthError, match="callback listener"):
        ms_oauth.start_email_oauth_login(
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            mailbox="bot@example.com",
        )


def test_callback_server_ignores_state_mismatch_and_keeps_waiting() -> None:
    """A stray or forged request with a bad state must not poison the queue —
    the real Microsoft redirect may still be on its way."""
    result_queue: queue.Queue = queue.Queue(maxsize=1)
    servers = ms_oauth._make_callback_servers("expected-state", result_queue)  # noqa: SLF001
    stop_event = threading.Event()
    threads = [
        threading.Thread(
            target=ms_oauth._serve_callback_server,  # noqa: SLF001
            args=(server, stop_event),
            daemon=True,
        )
        for server in servers
    ]
    for thread in threads:
        thread.start()
    port = servers[0].server_address[1]
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/callback?code=abc&state=wrong-state", timeout=5
        ).read()
        assert result_queue.empty()

        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/callback?code=abc&state=expected-state", timeout=5
        ).read()
        result = result_queue.get(timeout=5)
        assert result.code == "abc"
        assert result.state == "expected-state"
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=2)


def _make_flow(**overrides: object) -> ms_oauth.EmailOAuthLoginFlow:
    fields: dict[str, object] = dict(
        authorization_url="https://example.com/authorize",
        tenant_id="tenant-1",
        client_id="client-1",
        client_secret="secret-1",
        mailbox="bot@example.com",
        state="expected-state",
        result_queue=queue.Queue(maxsize=1),
        servers=[],
        timeout_s=60,
    )
    fields.update(overrides)
    return ms_oauth.EmailOAuthLoginFlow(**fields)  # type: ignore[arg-type]


def test_complete_rejects_bare_authorization_code() -> None:
    """The headless prompt only accepts a full callback URL — a bare code has
    no state and can never pass verification, so it must fail fast with a
    clear message instead of a confusing downstream state-mismatch error."""
    flow = _make_flow()
    try:
        with pytest.raises(MicrosoftOAuthError, match="full callback URL"):
            flow.complete("some-bare-code")
    finally:
        flow.cancel()
