"""Nonblocking GitHub device authorization for gateway settings clients."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import threading
import time

from oauth_cli_kit.models import OAuthToken

from nanobot.providers.github_copilot_provider import login_github_copilot


class GitHubCopilotOAuthFlow:
    """Expose the device prompt while the existing login worker waits for approval."""

    def __init__(self) -> None:
        self.authorization_url = ""
        self.user_code = ""
        self._deadline = time.monotonic() + 900
        self._ready = threading.Event()
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._token: OAuthToken | None = None
        self._error: Exception | None = None

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self._deadline - time.monotonic()))

    @property
    def expired(self) -> bool:
        return self._cancelled.is_set() or self.remaining_seconds <= 0

    def cancel(self) -> None:
        self._cancelled.set()

    def _authorize(self, url: str, code: str, expires_in: int) -> None:
        self.authorization_url = url
        self.user_code = code
        self._deadline = time.monotonic() + expires_in
        self._ready.set()

    def _run(self) -> None:
        try:
            self._token = login_github_copilot(
                print_fn=lambda _message: None,
                on_authorization=self._authorize,
                cancelled=self._cancelled,
                open_browser=False,
            )
        except Exception as exc:
            self._error = exc
        finally:
            self._done.set()
            self._ready.set()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="github-device-login").start()
        if not self._ready.wait(timeout=15):
            self.cancel()
            raise RuntimeError("GitHub sign-in timed out. Start again.")
        if self._error is not None:
            raise self._error

    def complete(self) -> OAuthToken | None:
        if not self._done.is_set():
            return None
        if self._error is not None:
            raise self._error
        return self._token
