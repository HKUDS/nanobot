"""xAI subscription OAuth (Authorization Code + PKCE) support.

This integration follows the public OAuth client contract used by Grok Build.
Credentials are stored separately from Grok Build so rotating refresh tokens are
never shared between the two applications.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock
from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.utils.helpers import _write_text_atomic

XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_CLIENT_VERSION = "0.2.109"
XAI_ALLOWED_CALLBACK_ORIGIN = "https://accounts.x.ai"
XAI_OAUTH_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "grok-cli:access",
    "api:access",
    "conversations:read",
    "conversations:write",
    "workspaces:read",
    "workspaces:write",
)

_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
_TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1000
_DEFAULT_TOKEN_TTL_S = 60 * 60
_HTTP_TIMEOUT_S = 15.0


class XAIOAuthError(RuntimeError):
    """An actionable xAI OAuth failure with no credential material."""


@dataclass(frozen=True)
class XAIToken:
    """Persisted xAI OAuth token material."""

    access: str
    refresh: str | None
    expires: int
    account_id: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> XAIToken | None:
        if not isinstance(value, dict):
            return None
        access = value.get("access")
        if not isinstance(access, str) or not access:
            return None
        refresh = value.get("refresh")
        if not isinstance(refresh, str) or not refresh:
            refresh = None
        try:
            expires = int(value.get("expires") or 0)
        except (TypeError, ValueError):
            expires = 0
        account_id = value.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            account_id = None
        return cls(access=access, refresh=refresh, expires=expires, account_id=account_id)


@dataclass(frozen=True)
class _Discovery:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None


@dataclass(frozen=True)
class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


class XAIOAuthLoginFlow:
    """Pending xAI OAuth login that can finish through loopback or an authorization code."""

    def __init__(
        self,
        *,
        authorization_url: str,
        redirect_uri: str,
        verifier: str,
        state: str,
        discovery: _Discovery,
        proxy: str | None,
        result_queue: queue.Queue[_CallbackResult],
        server: ThreadingHTTPServer,
        timeout_s: float,
    ) -> None:
        self.authorization_url = authorization_url
        self.redirect_uri = redirect_uri
        self._verifier = verifier
        self._state = state
        self._discovery = discovery
        self._proxy = proxy
        self._result_queue = result_queue
        self._server = server
        self._expires_at = time.monotonic() + timeout_s
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._token: XAIToken | None = None
        self._error: Exception | None = None
        self._closed = False
        self._server_thread = threading.Thread(
            target=_serve_callback_server,
            args=(server, self._stop_event),
            name="nanobot-xai-grok-oauth-callback",
            daemon=True,
        )
        self._server_thread.start()
        self._timeout_timer = threading.Timer(timeout_s, self._expire)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._expires_at

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self._expires_at - time.monotonic()))

    def complete(self, authorization_code: str | None = None) -> XAIToken | None:
        """Complete this flow, or return ``None`` while loopback is still pending."""
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()

        callback: _CallbackResult | None
        if authorization_code is not None:
            callback = _CallbackResult(code=authorization_code.strip())
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

    def wait(self, timeout_s: float) -> XAIToken:
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
            raise XAIOAuthError(
                "Timed out waiting for xAI sign-in. Run "
                "`nanobot provider login xai-grok` to try again."
            ) from exc
        return self._finish(callback)

    def cancel(self) -> None:
        """Stop the callback listener for an abandoned flow."""
        with self._lock:
            if self._token is None and self._error is None:
                self._error = XAIOAuthError("xAI sign-in was cancelled.")
            self._close_locked()

    def _finish(self, callback: _CallbackResult) -> XAIToken:
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
            self._close_locked()
            try:
                token = _exchange_callback(
                    callback,
                    expected_state=self._state,
                    discovery=self._discovery,
                    verifier=self._verifier,
                    redirect_uri=self.redirect_uri,
                    proxy=self._proxy,
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
        self._error = XAIOAuthError("xAI sign-in expired. Start a new sign-in flow.")
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
        if threading.current_thread() is not self._server_thread:
            self._server_thread.join(timeout=2)


def get_xai_oauth_storage_path() -> Path:
    """Return the instance-scoped xAI OAuth credential path."""
    return get_data_dir() / "auth" / "xai.json"


def get_xai_oauth_login_status() -> XAIToken | None:
    """Return locally stored login state without making a network request."""
    return _load_token()


def logout_xai_oauth() -> bool:
    """Remove this instance's credentials while excluding token refreshes."""
    path = get_xai_oauth_storage_path()
    with _token_lock():
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


def login_xai_oauth(
    *,
    print_fn: Callable[[str], None] = print,
    prompt_fn: Callable[[str], str] | None = None,
    proxy: str | None = None,
    callback_timeout_s: float = 600,
    browser_opener: Callable[[str], bool] = webbrowser.open,
) -> XAIToken:
    """Run xAI's browser-based OAuth flow and persist the resulting token.

    ``prompt_fn`` is used only when no local browser could be opened. It lets a
    headless user paste either the final callback URL or its authorization code.
    """
    flow = start_xai_oauth_login(proxy=proxy, timeout_s=callback_timeout_s)

    try:
        print_fn("Opening xAI sign-in in your browser...")
        print_fn(f"If it does not open automatically, visit:\n{flow.authorization_url}")
        opened = False
        with suppress(Exception):
            opened = bool(browser_opener(flow.authorization_url))

        if not opened and prompt_fn is not None:
            pasted = prompt_fn("Paste the final callback URL (or authorization code)")
            token = flow.complete(pasted)
            if token is None:  # pragma: no cover - pasted input always resolves a callback
                raise XAIOAuthError("xAI sign-in returned no authorization code.")
            return token
        return flow.wait(callback_timeout_s)
    finally:
        flow.cancel()


def start_xai_oauth_login(
    *,
    proxy: str | None = None,
    timeout_s: float = 600,
) -> XAIOAuthLoginFlow:
    """Create a non-blocking OAuth flow for browser or pasted-callback completion."""
    discovery = _discover(proxy)
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    result_queue: queue.Queue[_CallbackResult] = queue.Queue(maxsize=1)
    server = _make_callback_server(state, result_queue)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    authorization_url = _build_authorize_url(
        discovery.authorization_endpoint,
        redirect_uri=redirect_uri,
        challenge=challenge,
        state=state,
        nonce=nonce,
    )
    return XAIOAuthLoginFlow(
        authorization_url=authorization_url,
        redirect_uri=redirect_uri,
        verifier=verifier,
        state=state,
        discovery=discovery,
        proxy=proxy,
        result_queue=result_queue,
        server=server,
        timeout_s=timeout_s,
    )


def complete_xai_oauth_login(
    flow: XAIOAuthLoginFlow,
    authorization_code: str | None = None,
) -> XAIToken | None:
    """Complete a pending login from loopback state or a pasted authorization code."""
    return flow.complete(authorization_code)


def get_xai_oauth_token(
    *,
    proxy: str | None = None,
    min_ttl_ms: int = _TOKEN_REFRESH_MARGIN_MS,
    force_refresh: bool = False,
) -> XAIToken:
    """Load a usable token, refreshing it under an inter-process lock when needed."""
    token = _load_token()
    if token is None:
        raise XAIOAuthError(
            "xAI is not signed in. Run `nanobot provider login xai-grok` first."
        )
    if not force_refresh and _token_is_fresh(token, min_ttl_ms):
        return token
    if not token.refresh:
        if not force_refresh and token.expires > _now_ms():
            return token
        raise XAIOAuthError(
            "The xAI login has expired and cannot be refreshed. "
            "Run `nanobot provider login xai-grok` again."
        )

    with _token_lock():
        latest = _load_token()
        if latest is None:
            raise XAIOAuthError(
                "xAI is not signed in. Run `nanobot provider login xai-grok` first."
            )
        if not force_refresh and _token_is_fresh(latest, min_ttl_ms):
            return latest
        if not latest.refresh:
            raise XAIOAuthError(
                "The xAI login has expired and cannot be refreshed. "
                "Run `nanobot provider login xai-grok` again."
            )
        refreshed = _refresh_token(latest, proxy)
        _write_token(refreshed)
        return refreshed


def _discover(proxy: str | None) -> _Discovery:
    try:
        with _http_client(proxy) as client:
            response = client.get(_DISCOVERY_URL)
    except httpx.HTTPError as exc:
        raise XAIOAuthError(f"Could not reach xAI sign-in: {type(exc).__name__}.") from exc
    if response.status_code != HTTPStatus.OK:
        raise _oauth_http_error(response, "discovery")
    try:
        payload = response.json()
    except ValueError as exc:
        raise XAIOAuthError("xAI sign-in discovery returned invalid JSON.") from exc
    if payload.get("issuer", "").rstrip("/") != XAI_OAUTH_ISSUER:
        raise XAIOAuthError("xAI sign-in discovery returned an unexpected issuer.")
    authorization_endpoint = _validate_xai_endpoint(
        payload.get("authorization_endpoint"), "authorization"
    )
    token_endpoint = _validate_xai_endpoint(payload.get("token_endpoint"), "token")
    userinfo_raw = payload.get("userinfo_endpoint")
    userinfo_endpoint = (
        _validate_xai_endpoint(userinfo_raw, "userinfo") if userinfo_raw else None
    )
    return _Discovery(authorization_endpoint, token_endpoint, userinfo_endpoint)


def _validate_xai_endpoint(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise XAIOAuthError(f"xAI sign-in discovery omitted the {label} endpoint.")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise XAIOAuthError(
            f"xAI sign-in discovery returned an unsafe {label} endpoint."
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "auth.x.ai"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise XAIOAuthError(f"xAI sign-in discovery returned an unsafe {label} endpoint.")
    return value


def _generate_pkce() -> tuple[str, str]:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _build_authorize_url(
    endpoint: str,
    *,
    redirect_uri: str,
    challenge: str,
    state: str,
    nonce: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": XAI_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": " ".join(XAI_OAUTH_SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "referrer": "nanobot",
    }
    return f"{endpoint}?{urlencode(params)}"


def _make_callback_server(
    expected_state: str,
    result_queue: queue.Queue[_CallbackResult],
) -> ThreadingHTTPServer:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/callback":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            params = parse_qs(parsed.query)
            code = _first(params, "code")
            received_state = _first(params, "state")
            error = _first(params, "error_description") or _first(params, "error")
            if code and received_state and hmac.compare_digest(received_state, expected_state):
                result = _CallbackResult(code=code, state=received_state)
                title = "Signed in to xAI"
                message = "You can close this tab and return to nanobot."
            elif code:
                result = _CallbackResult(error="OAuth state mismatch")
                title = "Sign-in failed"
                message = "The sign-in response could not be verified. Return to nanobot and retry."
            else:
                result = _CallbackResult(error=error or "access denied")
                title = "Access denied"
                message = "Return to nanobot and try signing in again."
            with suppress(queue.Full):
                result_queue.put_nowait(result)
            body = _callback_page(title, message)
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            if origin == XAI_ALLOWED_CALLBACK_ORIGIN:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def log_message(self, _format: str, *_args: Any) -> None:
            # Callback query strings contain an authorization code.
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)


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
    discovery: _Discovery,
    verifier: str,
    redirect_uri: str,
    proxy: str | None,
) -> XAIToken:
    if callback.error:
        raise XAIOAuthError(f"xAI sign-in was not completed: {callback.error}")
    if not callback.code:
        raise XAIOAuthError("xAI sign-in returned no authorization code.")
    if callback.state and not hmac.compare_digest(callback.state, expected_state):
        raise XAIOAuthError("xAI sign-in failed because the OAuth state did not match.")

    payload = _exchange_code(
        discovery.token_endpoint,
        code=callback.code,
        verifier=verifier,
        redirect_uri=redirect_uri,
        proxy=proxy,
    )
    account_id = _fetch_account(discovery.userinfo_endpoint, payload["access_token"], proxy)
    return _token_from_response(payload, account_id=account_id)


def _exchange_code(
    token_endpoint: str,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    proxy: str | None,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": XAI_CLIENT_ID,
        "code_verifier": verifier,
    }
    try:
        with _http_client(proxy) as client:
            response = client.post(
                token_endpoint,
                data=data,
                headers={"x-grok-client-version": XAI_CLIENT_VERSION},
            )
    except httpx.HTTPError as exc:
        raise XAIOAuthError(f"Could not exchange the xAI sign-in code: {type(exc).__name__}.") from exc
    if not response.is_success:
        raise _oauth_http_error(response, "token exchange")
    return _token_payload(response)


def _refresh_token(token: XAIToken, proxy: str | None) -> XAIToken:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh or "",
        "client_id": XAI_CLIENT_ID,
    }
    try:
        with _http_client(proxy) as client:
            response = client.post(
                f"{XAI_OAUTH_ISSUER}/oauth2/token",
                data=data,
                headers={"x-grok-client-version": XAI_CLIENT_VERSION},
            )
    except httpx.HTTPError as exc:
        raise XAIOAuthError(f"Could not refresh the xAI login: {type(exc).__name__}.") from exc
    if not response.is_success:
        raise _oauth_http_error(response, "token refresh")
    payload = _token_payload(response)
    return _token_from_response(
        payload,
        account_id=token.account_id,
        previous_refresh=token.refresh,
    )


def _token_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise XAIOAuthError("xAI sign-in returned an invalid token response.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise XAIOAuthError("xAI sign-in returned no access token.")
    return payload


def _token_from_response(
    payload: dict[str, Any],
    *,
    account_id: str | None,
    previous_refresh: str | None = None,
) -> XAIToken:
    try:
        expires_in = max(1, int(payload.get("expires_in") or _DEFAULT_TOKEN_TTL_S))
    except (TypeError, ValueError):
        expires_in = _DEFAULT_TOKEN_TTL_S
    refresh = payload.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        refresh = previous_refresh
    return XAIToken(
        access=payload["access_token"],
        refresh=refresh,
        expires=_now_ms() + expires_in * 1000,
        account_id=account_id,
    )


def _fetch_account(endpoint: str | None, access_token: str, proxy: str | None) -> str | None:
    if not endpoint:
        return None
    try:
        with _http_client(proxy) as client:
            response = client.get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
        if not response.is_success:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("email", "preferred_username", "name", "sub"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _oauth_http_error(response: httpx.Response, action: str) -> XAIOAuthError:
    code: str | None = None
    description: str | None = None
    with suppress(ValueError):
        payload = response.json()
        if isinstance(payload, dict):
            raw_code = payload.get("error")
            raw_description = payload.get("error_description") or payload.get("message")
            code = raw_code[:80] if isinstance(raw_code, str) else None
            description = raw_description[:200] if isinstance(raw_description, str) else None
    detail = ": ".join(value for value in (code, description) if value)
    suffix = f" ({detail})" if detail else ""
    return XAIOAuthError(f"xAI OAuth {action} failed with HTTP {response.status_code}{suffix}.")


def _http_client(proxy: str | None) -> httpx.Client:
    kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT_S}
    if proxy:
        kwargs.update(proxy=proxy, trust_env=False)
    return httpx.Client(**kwargs)


def _token_lock() -> FileLock:
    path = get_xai_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_suffix(".lock")), timeout=15)


def _load_token() -> XAIToken | None:
    path = get_xai_oauth_storage_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read xAI OAuth credentials: {}", type(exc).__name__)
        return None
    return XAIToken.from_dict(payload)


def _write_token(token: XAIToken) -> None:
    path = get_xai_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(path.parent, 0o700)
    _write_text_atomic(path, json.dumps(asdict(token), indent=2, ensure_ascii=False))
    with suppress(OSError):
        os.chmod(path, 0o600)


def _token_is_fresh(token: XAIToken, min_ttl_ms: int) -> bool:
    return bool(token.access and token.expires > _now_ms() + max(0, min_ttl_ms))


def _now_ms() -> int:
    return int(time.time() * 1000)
