"""Token storage for nanobot auth."""

from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class AuthInfo:
    token: str
    server_url: str
    expires_at: float | None = None


def _auth_file_path() -> Path:
    return Path.home() / ".nanobot" / "auth.json"


def load_auth() -> AuthInfo | None:
    """Load saved auth info from disk."""
    path = _auth_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AuthInfo(
            token=data["token"],
            server_url=data["server_url"],
            expires_at=data.get("expires_at"),
        )
    except (json.JSONDecodeError, KeyError):
        return None


def save_auth(info: AuthInfo) -> None:
    """Save auth info to disk."""
    path = _auth_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "token": info.token,
        "server_url": info.server_url,
    }
    if info.expires_at is not None:
        data["expires_at"] = info.expires_at
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    path.chmod(0o600)


def delete_auth() -> bool:
    """Delete saved auth info. Returns True if file was deleted."""
    path = _auth_file_path()
    if path.exists():
        path.unlink()
        return True
    return False
