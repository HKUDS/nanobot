"""Codex OAuth token helpers for inference."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _resolve_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("~/.codex").expanduser()


def get_codex_auth_path() -> Path:
    """Return Codex auth.json path."""
    return _resolve_codex_home() / "auth.json"


def read_codex_access_token() -> str | None:
    """
    Read Codex OAuth access token from Codex CLI auth store.

    Expected file shape:
      {
        "tokens": {
          "access_token": "...",
          "refresh_token": "..."
        }
      }
    """
    auth_path = get_codex_auth_path()
    if not auth_path.exists():
        return None

    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    return access_token.strip()


def has_codex_oauth_token() -> bool:
    """Whether Codex OAuth credentials are available on disk."""
    return read_codex_access_token() is not None
