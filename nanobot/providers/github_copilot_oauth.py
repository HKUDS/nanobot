"""Nonblocking GitHub device authorization for gateway settings clients."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import threading
import time

from oauth_cli_kit.models import OAuthToken

from nanobot.providers import github_copilot_provider
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
        self._commit_lock = threading.Lock()
        self._saved = False

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self._deadline - time.monotonic()))

    @property
    def expired(self) -> bool:
        return self._cancelled.is_set() or self.remaining_seconds <= 0

    def cancel(self) -> None:
        with self._commit_lock:
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
                persist=False,
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
            raise RuntimeError("GitHub sign-in failed. Start again.") from None

    def complete(self) -> OAuthToken | None:
        # Approval alone must not change credentials after the UI was closed.
        # Commit only through the live flow's completion endpoint, serialized
        # with cancellation (including sign-out).
        with self._commit_lock:
            if self.expired:
                raise RuntimeError("GitHub sign-in expired or cancelled. Start again.")
            if not self._done.is_set():
                return None
            if self._error is not None or self._token is None or not self._token.access:
                raise RuntimeError("GitHub sign-in failed. Start again.") from None
            if not self._saved:
                github_copilot_provider.get_storage().save(self._token)
                self._saved = True
            return self._token
