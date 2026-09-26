"""Microsoft identity platform OAuth (Authorization Code) for the email channel.

Delegated user auth against an Office365/Outlook mailbox, used to obtain XOAUTH2
access tokens for IMAP/SMTP. Confidential client (app registration has a client
secret), so the code exchange and refresh calls include ``client_secret``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import secrets
import socket
import threading
import time
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock
from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

MS_OAUTH_SCOPES = (
    "offline_access",
    "https://outlook.office365.com/IMAP.AccessAsUser.All",
    "https://outlook.office365.com/SMTP.Send",
)
# Not 8765: that's nanobot's own default WebSocket/WebUI channel port
# (nanobot/channels/websocket/runtime.py), which is on by default and would
# already own this port on any real deployment.
MS_CALLBACK_PORT = 45219
MS_REDIRECT_URI = f"http://localhost:{MS_CALLBACK_PORT}/callback"
_TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1000
_DEFAULT_TOKEN_TTL_S = 60 * 60
_HTTP_TIMEOUT_S = 15.0


class MicrosoftOAuthError(RuntimeError):
    """An actionable Microsoft OAuth failure with no credential material."""


@dataclass(frozen=True)
class MSOAuthToken:
    """Persisted Microsoft OAuth token material for one mailbox."""

    access: str
    refresh: str | None
    expires: int
    scope: str
    fingerprint: str

    @classmethod
    def from_dict(cls, value: Any) -> MSOAuthToken | None:
        if not isinstance(value, dict):
            return None
        data = cast(dict[str, Any], value)
        access = data.get("access")
        if not isinstance(access, str) or not access:
            return None
        refresh = data.get("refresh")
        if not isinstance(refresh, str) or not refresh:
            refresh = None
        try:
            expires = int(data.get("expires") or 0)
        except (TypeError, ValueError):
            expires = 0
        scope = data.get("scope")
        scope = scope if isinstance(scope, str) else ""
        fingerprint = data.get("fingerprint")
        fingerprint = fingerprint if isinstance(fingerprint, str) else ""
        return cls(
            access=access, refresh=refresh, expires=expires, scope=scope, fingerprint=fingerprint
        )


@dataclass(frozen=True)
class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def account_fingerprint(tenant_id: str, client_id: str, mailbox: str) -> str:
    """Fingerprint the (tenant, app, mailbox) triple so a stored token isn't reused
    after the email channel is reconfigured for a different tenant/app/mailbox."""
    raw = f"{tenant_id.strip()}|{client_id.strip()}|{mailbox.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class EmailOAuthLoginFlow:
    """Pending Microsoft OAuth login that finishes through the loopback callback
    or a pasted authorization response."""

    def __init__(
        self,
        *,
        authorization_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox: str,
        state: str,
        result_queue: queue.Queue[_CallbackResult],
        servers: list[ThreadingHTTPServer],
        timeout_s: float,
    ) -> None:
        self.authorization_url = authorization_url
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._mailbox = mailbox
        self._state = state
        self._result_queue = result_queue
        self._servers = servers
        self._expires_at = time.monotonic() + timeout_s
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._token: MSOAuthToken | None = None
        self._error: Exception | None = None
        self._closed = False
        self._server_threads = [
            threading.Thread(
                target=_serve_callback_server,
                args=(server, self._stop_event),
                name="nanobot-email-ms-oauth-callback",
                daemon=True,
            )
            for server in servers
        ]
        for thread in self._server_threads:
            thread.start()
        self._timeout_timer = threading.Timer(timeout_s, self._expire)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._expires_at

    def complete(self, callback_url: str | None = None) -> MSOAuthToken | None:
        """Complete this flow, or return ``None`` while loopback is still pending.

        ``callback_url`` must be the full URL the browser was redirected to —
        without PKCE, the ``state`` query parameter it carries is the only
        defense against exchanging a code that belongs to an unrelated
        authorization flow, so a bare authorization code cannot be accepted.
        """
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()

        callback: _CallbackResult | None
        if callback_url is not None:
            candidate = callback_url.strip()
            if not candidate.startswith("http"):
                raise MicrosoftOAuthError(
                    "Paste the full callback URL you were redirected to, not just the "
                    "authorization code."
                )
            parsed = urlsplit(candidate)
            params = parse_qs(parsed.query)
            code = _first(params, "code")
            received_state = _first(params, "state")
            error = _first(params, "error_description") or _first(params, "error")
            callback = _CallbackResult(code=code, state=received_state, error=error)
        else:
            try:
                callback = self._result_queue.get_nowait()
            except queue.Empty:
                callback = None
        if callback is None:
            with self._lock:
                if self._token is not None:
                    return self._token
                self._raise_if_finished()
                if self.expired:
                    self._expire_locked()
                    self._raise_if_finished()
            return None
        return self._finish(callback)

    def wait(self, timeout_s: float) -> MSOAuthToken:
        """Wait for the loopback callback and complete this flow."""
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
        try:
            callback = self._result_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            with self._lock:
                if self._error is not None:
                    raise self._error
            raise MicrosoftOAuthError(
                "Timed out waiting for Microsoft sign-in. Run "
                "`nanobot channels login email` to try again."
            ) from exc
        return self._finish(callback)

    def cancel(self) -> None:
        """Stop the callback listener for an abandoned flow."""
        with self._lock:
            if self._token is None and self._error is None:
                self._error = MicrosoftOAuthError("Microsoft sign-in was cancelled.")
            self._close_locked()

    def _finish(self, callback: _CallbackResult) -> MSOAuthToken:
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
            self._close_locked()
            try:
                token = _exchange_callback(
                    callback,
                    expected_state=self._state,
                    tenant_id=self._tenant_id,
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                    mailbox=self._mailbox,
                )
                with _token_lock():
                    _write_token(token)
            except Exception as exc:
                self._error = exc
                raise
            self._token = token
            return token

    def _expire(self) -> None:
        with self._lock:
            if self._token is not None or self._error is not None:
                return
            self._expire_locked()

    def _expire_locked(self) -> None:
        self._error = MicrosoftOAuthError("Microsoft sign-in expired. Start a new sign-in flow.")
        self._close_locked()

    def _raise_if_finished(self) -> None:
        if self._token is not None:
            return
        if self._error is not None:
            raise self._error

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timeout_timer.cancel()
        self._stop_event.set()
        for thread in self._server_threads:
            if threading.current_thread() is not thread:
                thread.join(timeout=2)


def get_email_oauth_storage_path() -> Path:
    """Return the storage path for the email channel's Microsoft OAuth token."""
    return get_data_dir() / "auth" / "email_office365.json"


def get_email_oauth_login_status(
    tenant_id: str, client_id: str, mailbox: str
) -> MSOAuthToken | None:
    """Return locally stored login state for this account, without a network request."""
    token = _load_token()
    if token is None or token.fingerprint != account_fingerprint(tenant_id, client_id, mailbox):
        return None
    return token


def logout_email_oauth() -> bool:
    """Remove the stored email OAuth credentials."""
    path = get_email_oauth_storage_path()
    with _token_lock():
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


def login_email_oauth(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    mailbox: str,
    print_fn: Callable[[str], None] = print,
    prompt_fn: Callable[[str], str] | None = None,
    callback_timeout_s: float = 600,
    browser_opener: Callable[[str], bool] = webbrowser.open,
) -> MSOAuthToken:
    """Run the Microsoft browser-based OAuth flow and persist the resulting token.

    ``prompt_fn`` is used only when no local browser could be opened. It lets a
    headless user paste the final callback URL.
    """
    flow = start_email_oauth_login(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        mailbox=mailbox,
        timeout_s=callback_timeout_s,
    )

    try:
        print_fn("Opening Microsoft sign-in in your browser...")
        print_fn(f"If it does not open automatically, visit:\n{flow.authorization_url}")
        opened = False
        with suppress(Exception):
            opened = bool(browser_opener(flow.authorization_url))

        if not opened and prompt_fn is not None:
            pasted = prompt_fn("Paste the final callback URL")
            token = flow.complete(pasted)
            if token is None:  # pragma: no cover - pasted input always resolves a callback
                raise MicrosoftOAuthError("Microsoft sign-in returned no authorization code.")
            return token
        return flow.wait(callback_timeout_s)
    finally:
        flow.cancel()


def start_email_oauth_login(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    mailbox: str,
    timeout_s: float = 600,
) -> EmailOAuthLoginFlow:
    """Create a non-blocking OAuth flow for browser or pasted-callback completion."""
    state = secrets.token_urlsafe(32)
    result_queue: queue.Queue[_CallbackResult] = queue.Queue(maxsize=1)
    # The registered redirect URI uses "localhost", which some systems resolve to
    # ::1 before 127.0.0.1. Listen on both loopback families on the same port so
    # the browser reaches us regardless of which address it picks.
    try:
        servers = _make_callback_servers(state, result_queue)
    except OSError as exc:
        raise MicrosoftOAuthError(
            f"Could not start the sign-in callback listener on port {MS_CALLBACK_PORT}: {exc}. "
            "Free that port and try again."
        ) from exc
    authorize_endpoint = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    authorization_url = _build_authorize_url(
        authorize_endpoint,
        client_id=client_id,
        state=state,
    )
    return EmailOAuthLoginFlow(
        authorization_url=authorization_url,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        mailbox=mailbox,
        state=state,
        result_queue=result_queue,
        servers=servers,
        timeout_s=timeout_s,
    )


def get_email_oauth_token(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    mailbox: str,
    min_ttl_ms: int = _TOKEN_REFRESH_MARGIN_MS,
    force_refresh: bool = False,
) -> MSOAuthToken:
    """Load a usable access token, refreshing it under an inter-process lock when needed."""
    fingerprint = account_fingerprint(tenant_id, client_id, mailbox)
    token = _load_token()
    if token is None or token.fingerprint != fingerprint:
        raise MicrosoftOAuthError(
            "Email account is not signed in with Microsoft OAuth. "
            "Run `nanobot channels login email` first."
        )
    if not force_refresh and _token_is_fresh(token, min_ttl_ms):
        return token
    if not token.refresh:
        raise MicrosoftOAuthError(
            "The Microsoft login has expired and cannot be refreshed. "
            "Run `nanobot channels login email` again."
        )

    with _token_lock():
        latest = _load_token()
        if latest is None or latest.fingerprint != fingerprint:
            raise MicrosoftOAuthError(
                "Email account is not signed in with Microsoft OAuth. "
                "Run `nanobot channels login email` first."
            )
        if not force_refresh and _token_is_fresh(latest, min_ttl_ms):
            return latest
        if not latest.refresh:
            raise MicrosoftOAuthError(
                "The Microsoft login has expired and cannot be refreshed. "
                "Run `nanobot channels login email` again."
            )
        refreshed = _refresh_token(
            latest,
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            fingerprint=fingerprint,
        )
        _write_token(refreshed)
        return refreshed


def _build_authorize_url(
    endpoint: str,
    *,
    client_id: str,
    state: str,
) -> str:
    # No PKCE: this is a confidential client (has a client_secret), and Azure AD
    # validates the redirect_uri against a different registered-URI bucket when
    # PKCE parameters are present (public/native client flow) versus when they
    # are absent (confidential/web client flow) — sending code_challenge here
    # caused AADSTS500113 against a redirect_uri only registered under "Web".
    params = {
        "response_type": "code",
        "response_mode": "query",
        "client_id": client_id,
        "redirect_uri": MS_REDIRECT_URI,
        "scope": " ".join(MS_OAUTH_SCOPES),
        "state": state,
    }
    return f"{endpoint}?{urlencode(params)}"


class _ThreadingHTTPServerV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _make_callback_servers(
    expected_state: str,
    result_queue: queue.Queue[_CallbackResult],
) -> list[ThreadingHTTPServer]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            params = parse_qs(parsed.query)
            code = _first(params, "code")
            received_state = _first(params, "state")
            error = _first(params, "error_description") or _first(params, "error")
            state_ok = bool(received_state) and hmac.compare_digest(received_state, expected_state)
            if code and state_ok:
                result: _CallbackResult | None = _CallbackResult(code=code, state=received_state)
                title = "Signed in to Microsoft"
                message = "You can close this tab and return to nanobot."
            elif (code or error) and state_ok:
                result = _CallbackResult(error=error or "access denied")
                title = "Access denied"
                message = "Return to nanobot and try signing in again."
            else:
                # Unrecognized or state-mismatched request (e.g. a stray probe or a
                # forged callback) — don't treat it as terminal. Show an error page
                # but keep listening for the legitimate Microsoft redirect.
                result = None
                title = "Sign-in failed"
                message = "The sign-in response could not be verified. Return to nanobot and retry."
            if result is not None:
                with suppress(queue.Full):
                    result_queue.put_nowait(result)
            body = _callback_page(title, message)
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *_args: Any) -> None:  # noqa: A002
            # Callback query strings contain an authorization code.
            return

    servers: list[ThreadingHTTPServer] = [
        ThreadingHTTPServer(("127.0.0.1", MS_CALLBACK_PORT), CallbackHandler)
    ]
    # "localhost" can resolve to ::1 before 127.0.0.1 (notably on macOS); listen on
    # both loopback families so the browser reaches us either way. IPv6 may be
    # unavailable in some environments — that's not fatal, IPv4 still works.
    with suppress(OSError):
        servers.append(_ThreadingHTTPServerV6(("::1", MS_CALLBACK_PORT), CallbackHandler))
    return servers


def _serve_callback_server(
    server: ThreadingHTTPServer,
    stop_event: threading.Event,
) -> None:
    server.timeout = 0.2
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def _callback_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f7fb;color:#172033;
font:16px/1.5 system-ui,sans-serif}}main{{max-width:30rem;margin:1.5rem;padding:2rem;border:1px solid #dfe4ee;
border-radius:18px;background:white;box-shadow:0 16px 50px #17203318}}h1{{margin:0 0 .65rem;font-size:1.5rem}}
p{{margin:0;color:#526078}}</style></head><body><main><h1>{title}</h1><p>{message}</p></main></body></html>"""


def _exchange_callback(
    callback: _CallbackResult,
    *,
    expected_state: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    mailbox: str,
) -> MSOAuthToken:
    if callback.error:
        raise MicrosoftOAuthError(f"Microsoft sign-in was not completed: {callback.error}")
    if not callback.code:
        raise MicrosoftOAuthError("Microsoft sign-in returned no authorization code.")
    # State must always be present and match — an authorization code with no
    # verifiable state (e.g. pasted as a bare code, not a full callback URL)
    # cannot be distinguished from a code belonging to an unrelated flow for
    # the same client_id/redirect_uri.
    if not callback.state or not hmac.compare_digest(callback.state, expected_state):
        raise MicrosoftOAuthError(
            "Microsoft sign-in could not be verified. Paste the full callback URL "
            "(including the state parameter), not just the authorization code."
        )

    token_endpoint = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = _exchange_code(
        token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        code=callback.code,
    )
    return _token_from_response(
        payload, fingerprint=account_fingerprint(tenant_id, client_id, mailbox)
    )


def _exchange_code(
    token_endpoint: str,
    *,
    client_id: str,
    client_secret: str,
    code: str,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": MS_REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": " ".join(MS_OAUTH_SCOPES),
    }
    try:
        with _http_client() as client:
            response = client.post(token_endpoint, data=data)
    except httpx.HTTPError as exc:
        raise MicrosoftOAuthError(
            f"Could not exchange the Microsoft sign-in code: {type(exc).__name__}."
        ) from exc
    if not response.is_success:
        raise _oauth_http_error(response, "token exchange")
    return _token_payload(response)


def _refresh_token(
    token: MSOAuthToken,
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    fingerprint: str,
) -> MSOAuthToken:
    token_endpoint = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh or "",
        "client_id": client_id,
        "client_secret": client_secret,
        # Microsoft binds refresh tokens to the originally granted resource(s);
        # replay the same scope string used at authorization time.
        "scope": token.scope or " ".join(MS_OAUTH_SCOPES),
    }
    try:
        with _http_client() as client:
            response = client.post(token_endpoint, data=data)
    except httpx.HTTPError as exc:
        raise MicrosoftOAuthError(
            f"Could not refresh the Microsoft login: {type(exc).__name__}."
        ) from exc
    if not response.is_success:
        raise _oauth_http_error(response, "token refresh")
    payload = _token_payload(response)
    return _token_from_response(
        payload,
        fingerprint=fingerprint,
        previous_refresh=token.refresh,
    )


def _token_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise MicrosoftOAuthError("Microsoft sign-in returned an invalid token response.") from exc
    if not isinstance(payload, dict):
        raise MicrosoftOAuthError("Microsoft sign-in returned no access token.")
    token_payload = cast(dict[str, Any], payload)
    if not isinstance(token_payload.get("access_token"), str):
        raise MicrosoftOAuthError("Microsoft sign-in returned no access token.")
    return token_payload


def _token_from_response(
    payload: dict[str, Any],
    *,
    fingerprint: str,
    previous_refresh: str | None = None,
) -> MSOAuthToken:
    try:
        expires_in = max(1, int(payload.get("expires_in") or _DEFAULT_TOKEN_TTL_S))
    except (TypeError, ValueError):
        expires_in = _DEFAULT_TOKEN_TTL_S
    refresh = payload.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        refresh = previous_refresh
    scope = payload.get("scope")
    scope = scope if isinstance(scope, str) and scope else " ".join(MS_OAUTH_SCOPES)
    return MSOAuthToken(
        access=payload["access_token"],
        refresh=refresh,
        expires=_now_ms() + expires_in * 1000,
        scope=scope,
        fingerprint=fingerprint,
    )


def _oauth_http_error(response: httpx.Response, action: str) -> MicrosoftOAuthError:
    code: str | None = None
    description: str | None = None
    with suppress(ValueError):
        payload = response.json()
        if isinstance(payload, dict):
            error_payload = cast(dict[str, Any], payload)
            raw_code = error_payload.get("error")
            raw_description = error_payload.get("error_description")
            code = raw_code[:80] if isinstance(raw_code, str) else None
            description = raw_description[:200] if isinstance(raw_description, str) else None
    detail = ": ".join(value for value in (code, description) if value)
    suffix = f" ({detail})" if detail else ""
    return MicrosoftOAuthError(
        f"Microsoft OAuth {action} failed with HTTP {response.status_code}{suffix}."
    )


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=_HTTP_TIMEOUT_S)


def _token_lock() -> FileLock:
    path = get_email_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_suffix(".lock")), timeout=15)


def _load_token() -> MSOAuthToken | None:
    path = get_email_oauth_storage_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read email OAuth credentials: {}", type(exc).__name__)
        return None
    return MSOAuthToken.from_dict(payload)


def _write_token(token: MSOAuthToken) -> None:
    path = get_email_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(path.parent, 0o700)
    _write_text_atomic(path, json.dumps(asdict(token), indent=2, ensure_ascii=False))
    with suppress(OSError):
        os.chmod(path, 0o600)


def _token_is_fresh(token: MSOAuthToken, min_ttl_ms: int) -> bool:
    return bool(token.access and token.expires > _now_ms() + max(0, min_ttl_ms))


def _now_ms() -> int:
    return int(time.time() * 1000)
