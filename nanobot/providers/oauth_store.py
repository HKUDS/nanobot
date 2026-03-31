"""OAuth credential store for Anthropic Claude Code tokens.

Two credential sources (in priority order):
1. ~/.nanobot/oauth_credentials.json  — written by nanobot after each refresh
2. ~/.claude/.credentials.json        — written by Claude CLI (claudeAiOauth format)

Only the nanobot file is written on refresh; the Claude CLI file is read-only.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from loguru import logger

_DEFAULT_STORE_PATH = Path.home() / ".nanobot" / "oauth_credentials.json"
_DEFAULT_CLI_CREDS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class OAuthCredentials:
    access_token: str
    refresh_token: str
    expires_at_ms: int  # Unix timestamp in milliseconds

    def is_expired(self, margin_ms: int = 5 * 60 * 1000) -> bool:
        """Return True if the token is expired or will expire within margin_ms."""
        now_ms = int(time.time() * 1000)
        return now_ms >= self.expires_at_ms - margin_ms


class OAuthCredentialStore:
    """Read/write OAuth credentials from disk."""

    def __init__(
        self,
        store_path: Path | None = None,
        claude_cli_creds_path: Path | None = None,
    ) -> None:
        self._store_path = store_path or _DEFAULT_STORE_PATH
        self._cli_path = claude_cli_creds_path or _DEFAULT_CLI_CREDS_PATH

    def load(self) -> OAuthCredentials | None:
        """Load credentials. Nanobot file takes precedence over Claude CLI file."""
        creds = self._load_nanobot()
        if creds is not None:
            return creds
        return self._load_claude_cli()

    def save(self, creds: OAuthCredentials) -> None:
        """Persist credentials to the nanobot store file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(creds)
        self._store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("OAuth credentials saved to {}", self._store_path)

    def _load_nanobot(self) -> OAuthCredentials | None:
        if not self._store_path.exists():
            return None
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            return OAuthCredentials(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at_ms=int(data["expires_at_ms"]),
            )
        except Exception as e:
            logger.warning("Failed to load nanobot OAuth credentials: {}", e)
            return None

    def _load_claude_cli(self) -> OAuthCredentials | None:
        if not self._cli_path.exists():
            return None
        try:
            data = json.loads(self._cli_path.read_text(encoding="utf-8"))
            oauth = data.get("claudeAiOauth", {})
            return OAuthCredentials(
                access_token=oauth["accessToken"],
                refresh_token=oauth["refreshToken"],
                expires_at_ms=int(oauth["expiresAt"]),
            )
        except Exception as e:
            logger.warning("Failed to load Claude CLI OAuth credentials: {}", e)
            return None


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

_ANTHROPIC_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_ANTHROPIC_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_REFRESH_MARGIN_MS = 5 * 60 * 1000  # refresh 5 min before actual expiry


async def refresh_anthropic_token(refresh_token: str) -> OAuthCredentials:
    """Exchange a refresh token for a new access token.

    Raises RuntimeError on failure (network error or non-2xx response).
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": _ANTHROPIC_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _ANTHROPIC_TOKEN_URL,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Anthropic OAuth token refresh failed (HTTP {e.response.status_code}): {e.response.text}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Anthropic OAuth token refresh request failed: {e}") from e

    try:
        data = response.json()
    except Exception as e:
        raise RuntimeError(f"Anthropic OAuth token refresh returned invalid JSON: {e}") from e

    now_ms = int(time.time() * 1000)
    return OAuthCredentials(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at_ms=now_ms + int(data["expires_in"]) * 1000 - _REFRESH_MARGIN_MS,
    )
