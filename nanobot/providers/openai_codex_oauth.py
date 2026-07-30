"""Non-blocking OpenAI Codex OAuth flow for browser and remote WebUI login."""

# oauth-cli-kit does not publish type stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import queue
import secrets
import socket
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from oauth_cli_kit.models import OAuthProviderConfig, OAuthToken
from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
from oauth_cli_kit.storage import FileTokenStorage

_HTTP_TIMEOUT_S = 30.0
_CALLBACK_PATH = "/auth/callback"
_CALLBACK_PORT = 1455


class OpenAICodexOAuthError(RuntimeError):
    """An actionable Codex OAuth failure that contains no credential material."""


class OpenAICodexOAuthInputError(OpenAICodexOAuthError):
    """A recoverable error in a callback URL pasted by the user."""


@dataclass(frozen=True)
class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


class OpenAICodexOAuthLoginFlow:
    """Pending Codex OAuth login completed by loopback or a pasted callback URL."""

    def __init__(
        self,
        *,
        authorization_url: str,
        verifier: str,
        state: str,
        proxy: str | None,
        result_queue: queue.Queue[_CallbackResult],
        server: ThreadingHTTPServer | None,
        timeout_s: float,
    ) -> None:
        self.authorization_url = authorization_url
        self._verifier = verifier
        self._state = state
        self._proxy = proxy
        self._result_queue = result_queue
        self._server = server
        self._expires_at = time.monotonic() + timeout_s
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._token: OAuthToken | None = None
        self._error: Exception | None = None
        self._closed = False
        self._server_thread: threading.Thread | None = None
        if server is not None:
            self._server_thread = threading.Thread(
                target=_serve_callback_server,
                args=(server, self._stop_event),
                name="nanobot-openai-codex-oauth-callback",
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

    def complete(self, callback_url: str | None = None) -> OAuthToken | None:
        """Complete the login or return ``None`` while loopback is still pending."""
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()

        callback: _CallbackResult | None
        if callback_url is not None:
            callback = _parse_callback_url(callback_url)
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

    def cancel(self) -> None:
        """Stop the callback listener for an abandoned flow."""
        with self._lock:
            if self._token is None and self._error is None:
                self._error = OpenAICodexOAuthError("OpenAI Codex sign-in was cancelled.")
            self._close_locked()

    def _finish(self, callback: _CallbackResult) -> OAuthToken:
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
            self._close_locked()
            try:
                if callback.error:
                    raise OpenAICodexOAuthError(
                        f"OpenAI Codex sign-in was not completed: {callback.error}"
                    )
                if not callback.code:
                    raise OpenAICodexOAuthError(
                        "OpenAI Codex sign-in returned no authorization code."
                    )
                if not callback.state or not hmac.compare_digest(callback.state, self._state):
                    raise OpenAICodexOAuthError(
                        "OpenAI Codex sign-in failed because the OAuth state did not match."
                    )
                token = _exchange_code(
                    callback.code,
                    verifier=self._verifier,
                    proxy=self._proxy,
                )
                _token_storage().save(token)
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
        self._error = OpenAICodexOAuthError(
            "OpenAI Codex sign-in expired. Start a new sign-in flow."
        )
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
        server_thread = self._server_thread
        if server_thread is not None and threading.current_thread() is not server_thread:
            server_thread.join(timeout=2)


def start_openai_codex_oauth_login(
    *,
    proxy: str | None = None,
    timeout_s: float = 600,
) -> OpenAICodexOAuthLoginFlow:
    """Create a non-blocking PKCE flow for loopback or remote callback completion."""
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)
    result_queue: queue.Queue[_CallbackResult] = queue.Queue(maxsize=1)
    server = _make_callback_server(state, result_queue)
    authorization_url = _build_authorization_url(
        OPENAI_CODEX_PROVIDER,
        challenge=challenge,
        state=state,
    )
    return OpenAICodexOAuthLoginFlow(
        authorization_url=authorization_url,
        verifier=verifier,
        state=state,
        proxy=proxy,
        result_queue=result_queue,
        server=server,
        timeout_s=timeout_s,
    )


def complete_openai_codex_oauth_login(
    flow: OpenAICodexOAuthLoginFlow,
    callback_url: str | None = None,
) -> OAuthToken | None:
    """Complete a pending Codex login from loopback or a full callback URL."""
    return flow.complete(callback_url)


def _generate_pkce() -> tuple[str, str]:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _build_authorization_url(
    provider: OAuthProviderConfig,
    *,
    challenge: str,
    state: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": provider.redirect_uri,
        "scope": provider.scope,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": provider.default_originator,
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


def _parse_callback_url(raw: str) -> _CallbackResult:
    value = raw.strip()
    if not value:
        raise OpenAICodexOAuthInputError("Paste the full callback URL from your browser.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise OpenAICodexOAuthInputError(
            "The callback URL is invalid. Copy the full URL from your browser's address bar."
        ) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or port != _CALLBACK_PORT
        or parsed.path != _CALLBACK_PATH
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OpenAICodexOAuthInputError(
            "Paste the full callback URL from your browser "
            "(http://localhost:1455/auth/callback?...)."
        )
    params = parse_qs(parsed.query)
    code = _first(params, "code")
    state = _first(params, "state")
    error = _first(params, "error_description") or _first(params, "error")
    if not state:
        raise OpenAICodexOAuthInputError(
            "The callback URL is missing OAuth state. Copy the entire browser address."
        )
    if not code and not error:
        raise OpenAICodexOAuthInputError(
            "The callback URL has no authorization result. Finish signing in, then copy it again."
        )
    return _CallbackResult(code=code, state=state, error=error)


def _make_callback_server(
    expected_state: str,
    result_queue: queue.Queue[_CallbackResult],
) -> ThreadingHTTPServer | None:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != _CALLBACK_PATH:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            params = parse_qs(parsed.query)
            code = _first(params, "code")
            received_state = _first(params, "state")
            error = _first(params, "error_description") or _first(params, "error")
            if code and received_state and hmac.compare_digest(received_state, expected_state):
                result = _CallbackResult(code=code, state=received_state)
                title = "Signed in to OpenAI Codex"
                message = "You can close this tab and return to nanobot."
            elif code:
                result = _CallbackResult(error="OAuth state mismatch", state=received_state)
                title = "Sign-in failed"
                message = "Return to nanobot and start a new sign-in."
            else:
                result = _CallbackResult(
                    error=error or "access denied",
                    state=received_state,
                )
                title = "Access denied"
                message = "Return to nanobot and try signing in again."
            with suppress(queue.Full):
                result_queue.put_nowait(result)
            self._send_callback_page(title, message)

        def _send_callback_page(self, title: str, message: str) -> None:
            encoded = _callback_page(title, message).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *_args: Any) -> None:  # noqa: A002
            # Callback request targets contain a short-lived authorization code.
            return

    try:
        addrinfos = socket.getaddrinfo("localhost", _CALLBACK_PORT, type=socket.SOCK_STREAM)
    except OSError:
        return None
    for family, _socket_type, _protocol, _canonical_name, sockaddr in addrinfos:
        try:
            class CallbackServer(ThreadingHTTPServer):
                address_family = family

            server_address = cast(
                tuple[str, int] | tuple[str, int, int, int],
                sockaddr,
            )
            return CallbackServer(server_address, CallbackHandler)
        except OSError:
            continue
    return None


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


def _callback_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f7fb;color:#172033;
font:16px/1.5 system-ui,sans-serif}}main{{max-width:30rem;margin:1.5rem;padding:2rem;border:1px solid #dfe4ee;
border-radius:18px;background:white;box-shadow:0 16px 50px #17203318}}h1{{margin:0 0 .65rem;font-size:1.5rem}}
p{{margin:0;color:#526078}}</style></head><body><main><h1>{title}</h1><p>{message}</p></main></body></html>"""


def _exchange_code(
    code: str,
    *,
    verifier: str,
    proxy: str | None,
) -> OAuthToken:
    provider = OPENAI_CODEX_PROVIDER
    try:
        with _http_client(proxy) as client:
            response = client.post(
                provider.token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": provider.client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": provider.redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise OpenAICodexOAuthError(
            f"Could not exchange the OpenAI Codex sign-in code: {type(exc).__name__}."
        ) from exc
    if not response.is_success:
        raise _oauth_http_error(response, "token exchange")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAICodexOAuthError(
            "OpenAI Codex sign-in returned an invalid token response."
        ) from exc
    if not isinstance(payload, dict):
        raise OpenAICodexOAuthError("OpenAI Codex sign-in returned no access token.")
    token_payload = cast(dict[str, Any], payload)
    access = token_payload.get("access_token")
    refresh = token_payload.get("refresh_token")
    expires_in = token_payload.get("expires_in")
    if (
        not isinstance(access, str)
        or not access
        or not isinstance(refresh, str)
        or not refresh
        or not isinstance(expires_in, int)
    ):
        raise OpenAICodexOAuthError(
            "OpenAI Codex sign-in returned incomplete token credentials."
        )
    return OAuthToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000 + expires_in * 1000),
        account_id=_decode_account_id(access, provider),
    )


def _decode_account_id(
    access_token: str,
    provider: OAuthProviderConfig,
) -> str | None:
    if not provider.jwt_claim_path or not provider.account_id_claim:
        return None
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    try:
        padding = "=" * (-len(parts[1]) % 4)
        raw_payload: object = json.loads(
            base64.urlsafe_b64decode(parts[1] + padding).decode("utf-8")
        )
    except (ValueError, TypeError):
        return None
    if not isinstance(raw_payload, dict):
        return None
    payload = cast(dict[str, object], raw_payload)
    auth = payload.get(provider.jwt_claim_path)
    if not isinstance(auth, dict):
        return None
    account_id = cast(dict[str, object], auth).get(provider.account_id_claim)
    return account_id if isinstance(account_id, str) and account_id else None


def _oauth_http_error(response: httpx.Response, action: str) -> OpenAICodexOAuthError:
    code: str | None = None
    description: str | None = None
    with suppress(ValueError):
        payload = response.json()
        if isinstance(payload, dict):
            error_payload = cast(dict[str, Any], payload)
            raw_code = error_payload.get("error")
            raw_description = error_payload.get("error_description") or error_payload.get("message")
            code = raw_code[:80] if isinstance(raw_code, str) else None
            description = raw_description[:200] if isinstance(raw_description, str) else None
    detail = ": ".join(value for value in (code, description) if value)
    suffix = f" ({detail})" if detail else ""
    return OpenAICodexOAuthError(
        f"OpenAI Codex OAuth {action} failed with HTTP {response.status_code}{suffix}."
    )


def _http_client(proxy: str | None) -> httpx.Client:
    kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT_S}
    if proxy:
        kwargs.update(proxy=proxy, trust_env=False)
    return httpx.Client(**kwargs)


def _token_storage() -> FileTokenStorage:
    return FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename)


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None
