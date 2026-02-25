"""Token storage helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Protocol

from platformdirs import user_data_dir

from oauth_cli_kit.models import OAuthToken


class TokenStorage(Protocol):
    """Abstract token storage interface."""

    def load(self) -> OAuthToken | None:
        ...

    def save(self, token: OAuthToken) -> None:
        ...

    def get_token_path(self) -> Path:
        ...


def _get_token_path(
    token_filename: str,
    app_name: str,
    data_dir: Path | None = None,
) -> Path:
    override = os.environ.get("OAUTH_CLI_KIT_TOKEN_PATH")
    if override:
        return Path(override)
    base_dir = data_dir or Path(user_data_dir(app_name, appauthor=False))
    return base_dir / "auth" / token_filename


def _load_token_file(path: Path) -> OAuthToken | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return OAuthToken(
            access=data["access"],
            refresh=data["refresh"],
            expires=int(data["expires"]),
            account_id=data.get("account_id"),
        )
    except Exception:
        return None


def _save_token_file(path: Path, token: OAuthToken) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access": token.access,
        "refresh": token.refresh,
        "expires": token.expires,
    }
    if token.account_id:
        payload["account_id"] = token.account_id
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except Exception:
        # Ignore permission setting failures.
        pass


def _try_import_codex_cli_token(path: Path) -> OAuthToken | None:
    codex_path = Path.home() / ".codex" / "auth.json"
    if not codex_path.exists():
        return None
    try:
        data = json.loads(codex_path.read_text(encoding="utf-8"))
        tokens = data.get("tokens") or {}
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        account_id = tokens.get("account_id")
        if not access or not refresh or not account_id:
            return None
        try:
            mtime = codex_path.stat().st_mtime
            expires = int(mtime * 1000 + 60 * 60 * 1000)
        except Exception:
            expires = int(time.time() * 1000 + 60 * 60 * 1000)
        token = OAuthToken(
            access=str(access),
            refresh=str(refresh),
            expires=expires,
            account_id=str(account_id),
        )
        _save_token_file(path, token)
        return token
    except Exception:
        return None


class FileTokenStorage:
    """File-based token storage."""

    def __init__(
        self,
        token_filename: str = "oauth.json",
        app_name: str = "oauth-cli-kit",
        data_dir: Path | None = None,
        import_codex_cli: bool = True,
    ) -> None:
        self._token_filename = token_filename
        self._app_name = app_name
        self._data_dir = data_dir
        self._import_codex_cli = import_codex_cli

    def get_token_path(self) -> Path:
        return _get_token_path(self._token_filename, self._app_name, self._data_dir)

    def load(self) -> OAuthToken | None:
        path = self.get_token_path()
        token = _load_token_file(path)
        if token:
            return token
        if self._import_codex_cli:
            return _try_import_codex_cli_token(path)
        return None

    def save(self, token: OAuthToken) -> None:
        _save_token_file(self.get_token_path(), token)


class _FileLock:
    """Simple file lock to reduce concurrent refreshes."""

    def __init__(self, path: Path):
        self._path = path
        self._fp = None

    def __enter__(self) -> "_FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self._path, "a+")
        try:
            import fcntl

            fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX)
        except Exception:
            # Non-POSIX or failed lock: continue without locking.
            pass
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            import fcntl

            fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            if self._fp:
                self._fp.close()
        except Exception:
            pass
