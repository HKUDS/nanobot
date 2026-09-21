"""PKCE OAuth flow state for Linear app installations."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from nanobot.channels.linear.config import LinearConfig

LINEAR_AUTHORIZE_URL = "https://linear.app/oauth/authorize"
LINEAR_SCOPES = ("read", "write", "app:mentionable")
FLOW_TTL_SECONDS = 600


@dataclass(slots=True)
class LinearOAuthFlow:
    session_id: str
    state: str
    verifier: str
    created_at: float
    deadline: float
    code: str | None = None
    error: str | None = None


class LinearOAuthFlows:
    """Process-local, short-lived OAuth state shared with the callback server."""

    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._by_state: dict[str, LinearOAuthFlow] = {}

    def create(self) -> LinearOAuthFlow:
        now = time.monotonic()
        flow = LinearOAuthFlow(
            session_id=secrets.token_urlsafe(18),
            state=secrets.token_urlsafe(32),
            verifier=secrets.token_urlsafe(64),
            created_at=time.time(),
            deadline=now + FLOW_TTL_SECONDS,
        )
        with self._guard:
            self._cleanup_locked(now)
            self._by_state[flow.state] = flow
        return flow

    def complete(self, state: str, *, code: str | None, error: str | None) -> bool:
        with self._guard:
            self._cleanup_locked(time.monotonic())
            flow = self._by_state.get(state)
            if flow is None or flow.code is not None or flow.error is not None:
                return False
            flow.code = code
            flow.error = error
            return True

    def remove(self, flow: LinearOAuthFlow) -> None:
        with self._guard:
            if self._by_state.get(flow.state) is flow:
                self._by_state.pop(flow.state, None)

    def _cleanup_locked(self, now: float) -> None:
        expired = [state for state, flow in self._by_state.items() if now >= flow.deadline]
        for state in expired:
            self._by_state.pop(state, None)


OAUTH_FLOWS = LinearOAuthFlows()


def authorization_url(config: LinearConfig, flow: LinearOAuthFlow) -> str:
    digest = hashlib.sha256(flow.verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": ",".join(LINEAR_SCOPES),
            "actor": "app",
            "prompt": "consent",
            "state": flow.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{LINEAR_AUTHORIZE_URL}?{query}"
