"""Claude Code subscription credential management.

Reads OAuth tokens from ~/.claude/.credentials.json (written by Claude Code).
Token refresh is left to Claude Code itself — refresh tokens are single-use,
so refreshing here would invalidate Claude Code's own session.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

CREDENTIALS_PATH = Path("~/.claude/.credentials.json").expanduser()
EXPIRY_BUFFER_MS = 5 * 60 * 1000  # warn 5 minutes before actual expiry


def read_credentials() -> dict:
    """Read the claudeAiOauth block from ~/.claude/.credentials.json."""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Claude Code credentials not found at {CREDENTIALS_PATH}. "
            "Please install Claude Code and log in first."
        )
    data = json.loads(CREDENTIALS_PATH.read_text())
    oauth = data.get("claudeAiOauth")
    if not oauth or not oauth.get("accessToken"):
        raise ValueError(
            "No claudeAiOauth credentials found in ~/.claude/.credentials.json. "
            "Please log in to Claude Code first."
        )
    return oauth


def is_expired(creds: dict) -> bool:
    """Check whether the access token is expired (with 5-minute buffer)."""
    expires_at = creds.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    return now_ms >= (expires_at - EXPIRY_BUFFER_MS)


def get_access_token() -> str:
    """Return the current access token from Claude Code credentials.

    Does NOT refresh — Claude Code manages its own token lifecycle.
    If the token is expired, raises an error telling the user to
    open Claude Code so it can refresh.
    """
    creds = read_credentials()
    if is_expired(creds):
        raise RuntimeError(
            "Claude Code OAuth token has expired. "
            "Open Claude Code (or run /login) to refresh it."
        )
    return creds["accessToken"]
