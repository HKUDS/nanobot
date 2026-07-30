"""WebUI adapter around oauth-cli-kit's interactive Codex login."""

# oauth-cli-kit does not publish type stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import hmac
import queue
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit, urlunsplit

from oauth_cli_kit import login_oauth_interactive
from oauth_cli_kit.models import OAuthToken
from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER

_AUTHORIZATION_URL_TIMEOUT_S = 5.0
_CALLBACK = urlsplit(OPENAI_CODEX_PROVIDER.redirect_uri)
_CALLBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_CALLBACK_PORT = _CALLBACK.port or 1455
_TOKEN_EXCHANGE_STATUS = re.compile(r"Token exchange failed:\s*(\d{3})\b")
_CALLBACK_RECEIVED_HTML = b"""<!doctype html>
<meta charset="utf-8">
<title>OpenAI Codex sign-in</title>
<p>Callback received. You can return to nanobot.</p>
"""


class OpenAICodexOAuthError(RuntimeError):
    """An actionable Codex OAuth failure that contains no credential material."""


class OpenAICodexOAuthInputError(OpenAICodexOAuthError):
    """A recoverable error in a callback URL pasted by the user."""


# The WebUI opens the browser itself. oauth-cli-kit closes its listener in that
# headless mode, so this relay preserves automatic local callbacks without
# taking ownership of PKCE, token exchange, or credential storage.
class _CallbackRelayHandler(BaseHTTPRequestHandler):
    """Relay the fixed loopback callback into oauth-cli-kit's prompt."""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path != _CALLBACK.path:
            self._send(HTTPStatus.NOT_FOUND, b"Not found")
            return
        callback_url = urlunsplit(
            (_CALLBACK.scheme, _CALLBACK.netloc, _CALLBACK.path, parsed.query, "")
        )
        try:
            cast(_CallbackRelayServer, self.server).submit_callback(callback_url)
        except OpenAICodexOAuthError:
            self._send(HTTPStatus.BAD_REQUEST, b"Invalid OAuth callback")
            return
        self._send(HTTPStatus.OK, _CALLBACK_RECEIVED_HTML, "text/html; charset=utf-8")

    def _send(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class _CallbackRelayServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, submit_callback: Callable[[str], object]) -> None:
        self.submit_callback = submit_callback
        super().__init__(("127.0.0.1", _CALLBACK_PORT), _CallbackRelayHandler)


def _start_callback_relay(
    submit_callback: Callable[[str], object],
) -> _CallbackRelayServer | None:
    try:
        server = _CallbackRelayServer(submit_callback)
    except OSError:
        return None
    thread = threading.Thread(
        target=server.serve_forever,
        name="nanobot-openai-codex-oauth-callback",
        daemon=True,
    )
    thread.start()
    return server


class OpenAICodexOAuthLoginFlow:
    """Expose oauth-cli-kit's blocking prompt as a two-stage WebUI flow."""

    def __init__(
        self,
        *,
        proxy: str | None,
        timeout_s: float,
        listen_for_callback: bool,
    ) -> None:
        self.authorization_url = ""
        self._expected_state = ""
        self._proxy = proxy
        self._expires_at = time.monotonic() + timeout_s
        self._callback_input: queue.Queue[str] = queue.Queue(maxsize=1)
        self._result: Future[OAuthToken] = Future()
        self._ready = threading.Event()
        self._submission_lock = threading.Lock()
        self._callback_server_lock = threading.Lock()
        self._submitted = False
        self._thread = threading.Thread(
            target=self._run,
            name="nanobot-openai-codex-oauth",
            daemon=True,
        )
        self._callback_server = (
            _start_callback_relay(self.complete) if listen_for_callback else None
        )

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._expires_at

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self._expires_at - time.monotonic()))

    def start(self) -> OpenAICodexOAuthLoginFlow:
        self._thread.start()
        wait_s = min(
            _AUTHORIZATION_URL_TIMEOUT_S,
            max(0.0, self._expires_at - time.monotonic()),
        )
        if not self._ready.wait(wait_s):
            error = OpenAICodexOAuthError(
                "OpenAI Codex sign-in could not create an authorization URL."
            )
            self._fail(error)
            raise error
        if self._result.done():
            self._result.result()
        if self.authorization_url:
            return self
        error = OpenAICodexOAuthError(
            "OpenAI Codex sign-in returned no authorization URL."
        )
        self._fail(error)
        raise error

    def complete(self, callback_url: str | None = None) -> OAuthToken | None:
        """Submit a full callback URL, or return ``None`` while waiting for one."""
        if self._result.done():
            return self._result.result()
        if self.expired:
            error = OpenAICodexOAuthError(
                "OpenAI Codex sign-in expired. Start a new sign-in flow."
            )
            self._fail(error)
            raise error
        if callback_url is None:
            return None

        callback_state, authorization_failed = _validate_callback_url(callback_url)
        if not hmac.compare_digest(callback_state, self._expected_state):
            raise OpenAICodexOAuthInputError(
                "The callback URL does not belong to this sign-in flow. Copy the latest URL."
            )
        if authorization_failed:
            error = OpenAICodexOAuthError(
                "OpenAI Codex sign-in was not completed by the authorization server."
            )
            self._fail(error)
            raise error

        with self._submission_lock:
            if self._submitted:
                return None
            self._submitted = True
            try:
                self._callback_input.put_nowait(callback_url.strip())
            except queue.Full:
                return None
        return self._result.result() if self._result.done() else None

    def cancel(self) -> None:
        """Unblock an abandoned interactive login."""
        self._fail(OpenAICodexOAuthError("OpenAI Codex sign-in was cancelled."))
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=0.5)

    def _run(self) -> None:
        try:
            token = login_oauth_interactive(
                print_fn=self._capture_output,
                prompt_fn=self._prompt_for_callback,
                provider=OPENAI_CODEX_PROVIDER,
                proxy=self._proxy,
                open_browser=False,
            )
        except Exception as exc:
            with suppress(Exception):
                self._result.set_exception(_safe_login_error(exc))
        else:
            with suppress(Exception):
                self._result.set_result(token)
        finally:
            self._stop_callback_relay()
            self._ready.set()

    def _capture_output(self, message: str) -> None:
        raw = str(message)
        start = raw.find(OPENAI_CODEX_PROVIDER.authorize_url)
        if start < 0:
            return
        candidate = raw[start:].split(maxsplit=1)[0]
        state = _first(parse_qs(urlsplit(candidate).query), "state")
        if not state:
            return
        self.authorization_url = candidate
        self._expected_state = state
        self._ready.set()

    def _prompt_for_callback(self, _prompt: str) -> str:
        remaining = max(0.0, self._expires_at - time.monotonic())
        try:
            value = self._callback_input.get(timeout=remaining)
        except queue.Empty as exc:
            raise OpenAICodexOAuthError(
                "OpenAI Codex sign-in expired. Start a new sign-in flow."
            ) from exc
        if not value:
            error = self._result.exception() if self._result.done() else None
            if error is not None:
                raise error
            raise OpenAICodexOAuthError("OpenAI Codex sign-in was cancelled.")
        return value

    def _fail(self, error: OpenAICodexOAuthError) -> None:
        try:
            self._result.set_exception(error)
        except Exception:
            pass
        else:
            with suppress(queue.Full):
                self._callback_input.put_nowait("")
        self._ready.set()
        self._stop_callback_relay()

    def _stop_callback_relay(self) -> None:
        with self._callback_server_lock:
            server = self._callback_server
            self._callback_server = None
        if server is None:
            return
        server.shutdown()
        server.server_close()


def start_openai_codex_oauth_login(
    *,
    proxy: str | None = None,
    timeout_s: float = 600,
    listen_for_callback: bool = True,
) -> OpenAICodexOAuthLoginFlow:
    """Start a non-blocking wrapper around oauth-cli-kit's Codex login."""
    return OpenAICodexOAuthLoginFlow(
        proxy=proxy,
        timeout_s=timeout_s,
        listen_for_callback=listen_for_callback,
    ).start()


def complete_openai_codex_oauth_login(
    flow: OpenAICodexOAuthLoginFlow,
    callback_url: str | None = None,
) -> OAuthToken | None:
    """Complete a pending Codex login from a full callback URL."""
    return flow.complete(callback_url)


def _validate_callback_url(raw: str) -> tuple[str, bool]:
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
        parsed.scheme != _CALLBACK.scheme
        or parsed.hostname not in _CALLBACK_HOSTS
        or port != _CALLBACK.port
        or parsed.path != _CALLBACK.path
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OpenAICodexOAuthInputError(
            f"Paste the full callback URL from your browser ({OPENAI_CODEX_PROVIDER.redirect_uri}?...)."
        )
    params = parse_qs(parsed.query)
    code = _first(params, "code")
    state = _first(params, "state")
    error = _first(params, "error")
    if not state:
        raise OpenAICodexOAuthInputError(
            "The callback URL is missing OAuth state. Copy the entire browser address."
        )
    if not code and not error:
        raise OpenAICodexOAuthInputError(
            "The callback URL has no authorization result. Finish signing in, then copy it again."
        )
    return state, error is not None


def _safe_login_error(exc: Exception) -> OpenAICodexOAuthError:
    if isinstance(exc, OpenAICodexOAuthError):
        return exc
    message = str(exc).strip()
    if message == "State validation failed.":
        return OpenAICodexOAuthError(
            "OpenAI Codex sign-in failed because the OAuth state did not match."
        )
    if message == "Authorization code not found.":
        return OpenAICodexOAuthError(
            "OpenAI Codex sign-in returned no authorization code."
        )
    status = _TOKEN_EXCHANGE_STATUS.search(message)
    if status:
        return OpenAICodexOAuthError(
            f"OpenAI Codex OAuth token exchange failed with HTTP {status.group(1)}."
        )
    return OpenAICodexOAuthError(
        f"OpenAI Codex sign-in failed ({type(exc).__name__})."
    )


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None
