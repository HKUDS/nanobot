"""WebUI adapter around oauth-cli-kit's interactive Codex login."""

# oauth-cli-kit does not publish type stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import hmac
import queue
import re
import threading
import time
from concurrent.futures import Future
from contextlib import suppress
from urllib.parse import parse_qs, urlsplit

from oauth_cli_kit import login_oauth_interactive
from oauth_cli_kit.models import OAuthToken
from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER

_AUTHORIZATION_URL_TIMEOUT_S = 5.0
_CALLBACK = urlsplit(OPENAI_CODEX_PROVIDER.redirect_uri)
_CALLBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_TOKEN_EXCHANGE_STATUS = re.compile(r"Token exchange failed:\s*(\d{3})\b")


class OpenAICodexOAuthError(RuntimeError):
    """An actionable Codex OAuth failure that contains no credential material."""


class OpenAICodexOAuthInputError(OpenAICodexOAuthError):
    """A recoverable error in a callback URL pasted by the user."""


class OpenAICodexOAuthLoginFlow:
    """Expose oauth-cli-kit's blocking prompt as a two-stage WebUI flow."""

    def __init__(
        self,
        *,
        proxy: str | None,
        timeout_s: float,
        open_browser: bool,
    ) -> None:
        self.authorization_url = ""
        self._expected_state = ""
        self._proxy = proxy
        self._open_browser = open_browser
        self._expires_at = time.monotonic() + timeout_s
        self._callback_input: queue.Queue[str] = queue.Queue(maxsize=1)
        self._result: Future[OAuthToken] = Future()
        self._ready = threading.Event()
        self._submission_lock = threading.Lock()
        self._submitted = False
        self._thread = threading.Thread(
            target=self._run,
            name="nanobot-openai-codex-oauth",
            daemon=True,
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
                open_browser=self._open_browser,
            )
        except Exception as exc:
            with suppress(Exception):
                self._result.set_exception(_safe_login_error(exc))
        else:
            with suppress(Exception):
                self._result.set_result(token)
        finally:
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


def start_openai_codex_oauth_login(
    *,
    proxy: str | None = None,
    timeout_s: float = 600,
    open_browser: bool = True,
) -> OpenAICodexOAuthLoginFlow:
    """Start a non-blocking wrapper around oauth-cli-kit's Codex login."""
    return OpenAICodexOAuthLoginFlow(
        proxy=proxy,
        timeout_s=timeout_s,
        open_browser=open_browser,
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
