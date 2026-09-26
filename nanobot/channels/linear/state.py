"""Durable installation and webhook state owned by the Linear channel."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from nanobot.config.paths import get_config_path, get_runtime_subdir


@dataclass(frozen=True, slots=True)
class LinearInstallation:
    organization_id: str
    oauth_client_id: str
    app_user_id: str
    access_token: str
    refresh_token: str
    expires_at: float
    scope: tuple[str, ...] = ()
    organization_name: str = ""
    # Store-owned lifecycle metadata, separate from the credential value's equality.
    authorized_at: float = field(default=0, compare=False)


@dataclass(frozen=True, slots=True)
class QueuedWebhook:
    delivery_id: str
    payload: dict[str, Any]
    attempts: int


class LinearStateStore:
    """Small SQLite store so webhook acknowledgement is durable and idempotent."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_runtime_subdir("linear") / "state.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._guard = threading.RLock()
        self._initialize()
        try:
            os.chmod(self.path.parent, 0o700)
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._guard, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS installations (
                    organization_id TEXT PRIMARY KEY,
                    oauth_client_id TEXT NOT NULL,
                    app_user_id TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    scope_json TEXT NOT NULL,
                    organization_name TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_events (
                    delivery_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_receipts (
                    delivery_id TEXT PRIMARY KEY,
                    received_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS member_access (
                    oauth_client_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
                    PRIMARY KEY (oauth_client_id, organization_id, user_id)
                );
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(installations)").fetchall()
            }
            if "oauth_client_id" not in columns:
                connection.execute(
                    "ALTER TABLE installations ADD COLUMN oauth_client_id TEXT NOT NULL DEFAULT ''"
                )
            if "authorized_at" not in columns:
                connection.execute(
                    "ALTER TABLE installations ADD COLUMN authorized_at REAL NOT NULL DEFAULT 0"
                )
            connection.execute(
                "DELETE FROM webhook_receipts WHERE received_at < ?",
                (time.time() - 30 * 24 * 60 * 60,),
            )

    def has_installations(self, oauth_client_id: str | None = None) -> bool:
        with self._guard, self._connect() as connection:
            if oauth_client_id is None:
                row = connection.execute("SELECT 1 FROM installations LIMIT 1").fetchone()
            else:
                row = connection.execute(
                    "SELECT 1 FROM installations WHERE oauth_client_id = ? LIMIT 1",
                    (oauth_client_id,),
                ).fetchone()
        return row is not None

    def save_installation(
        self, installation: LinearInstallation, *, reauthorize: bool = False,
    ) -> None:
        now = time.time()
        with self._guard, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO installations (
                    organization_id, oauth_client_id, app_user_id, access_token, refresh_token,
                    expires_at, scope_json, organization_name, updated_at, authorized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id) DO UPDATE SET
                    oauth_client_id=excluded.oauth_client_id,
                    app_user_id=excluded.app_user_id,
                    access_token=excluded.access_token,
                    refresh_token=excluded.refresh_token,
                    expires_at=excluded.expires_at,
                    scope_json=excluded.scope_json,
                    organization_name=excluded.organization_name,
                    updated_at=excluded.updated_at,
                    authorized_at=CASE
                        WHEN ? OR installations.oauth_client_id != excluded.oauth_client_id
                        THEN excluded.authorized_at ELSE installations.authorized_at END
                """,
                (
                    installation.organization_id,
                    installation.oauth_client_id,
                    installation.app_user_id,
                    installation.access_token,
                    installation.refresh_token,
                    installation.expires_at,
                    json.dumps(installation.scope),
                    installation.organization_name,
                    now,
                    now,
                    reauthorize,
                ),
            )

    def refresh_installation(
        self, previous: LinearInstallation, refreshed: LinearInstallation,
    ) -> bool:
        """Rotate only the credentials read before the request, never insert a grant."""
        if (refreshed.organization_id != previous.organization_id
                or refreshed.oauth_client_id != previous.oauth_client_id):
            raise ValueError("A token refresh cannot change the Linear workspace or app")
        with self._guard, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE installations
                SET access_token = ?, refresh_token = ?, expires_at = ?, scope_json = ?, updated_at = ?
                WHERE organization_id = ? AND oauth_client_id = ? AND authorized_at = ?
                    AND access_token = ? AND refresh_token = ?
                """,
                (refreshed.access_token, refreshed.refresh_token, refreshed.expires_at,
                 json.dumps(refreshed.scope), time.time(), previous.organization_id,
                 previous.oauth_client_id, previous.authorized_at,
                 previous.access_token, previous.refresh_token),
            )
            return result.rowcount == 1

    def installation(self, organization_id: str) -> LinearInstallation | None:
        with self._guard, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM installations WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
        return _installation_from_row(row) if row is not None else None

    def list_installations(
        self,
        oauth_client_id: str | None = None,
    ) -> list[LinearInstallation]:
        """Return installations, optionally restricted to one OAuth client."""
        with self._guard, self._connect() as connection:
            if oauth_client_id is None:
                rows = connection.execute(
                    "SELECT * FROM installations ORDER BY organization_name, organization_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM installations
                    WHERE oauth_client_id = ?
                    ORDER BY organization_name, organization_id
                    """,
                    (oauth_client_id,),
                ).fetchall()
        return [_installation_from_row(row) for row in rows]

    def delete_installation(
        self, organization_id: str, *, oauth_client_id: str | None = None,
        revoked_at: float | None = None, expected: LinearInstallation | None = None,
    ) -> bool:
        """Remove an installation, ignoring revocations from an older authorization."""
        with self._guard, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM installations WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
            if current is None:
                return False
            if expected is not None and (
                _installation_from_row(current) != expected
                or float(current["authorized_at"]) != expected.authorized_at
            ):
                return False
            if oauth_client_id is not None and current["oauth_client_id"] != oauth_client_id:
                return False
            if revoked_at is not None and revoked_at < float(current["authorized_at"]):
                return False
            connection.execute(
                "DELETE FROM member_access WHERE organization_id = ? "
                "AND oauth_client_id IN (SELECT oauth_client_id FROM installations "
                "WHERE organization_id = ?)",
                (organization_id, organization_id),
            )
            connection.execute(
                "DELETE FROM installations WHERE organization_id = ?",
                (organization_id,),
            )
        return True

    def member_access(self, client_id: str, organization_id: str, user_id: str) -> bool | None:
        """An explicit choice overrides legacy pairing and allowFrom, including '*'."""
        with self._guard, self._connect() as connection:
            row = connection.execute(
                "SELECT allowed FROM member_access "
                "WHERE oauth_client_id = ? AND organization_id = ? AND user_id = ?",
                (client_id, organization_id, user_id),
            ).fetchone()
        return bool(row["allowed"]) if row is not None else None

    def set_member_access(
        self, client_id: str, organization_id: str, user_id: str, *, allowed: bool,
    ) -> None:
        with self._guard, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            installed = connection.execute(
                "SELECT 1 FROM installations WHERE oauth_client_id = ? AND organization_id = ?",
                (client_id, organization_id),
            ).fetchone()
            if installed is None:
                raise ValueError("Linear workspace is not connected")
            connection.execute(
                "INSERT INTO member_access (oauth_client_id, organization_id, user_id, allowed) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(oauth_client_id, organization_id, user_id) "
                "DO UPDATE SET allowed = excluded.allowed",
                (client_id, organization_id, user_id, int(allowed)),
            )

    def enqueue_webhook(self, delivery_id: str, payload: dict[str, Any]) -> bool:
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with self._guard, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            receipt = connection.execute(
                "INSERT OR IGNORE INTO webhook_receipts (delivery_id, received_at) VALUES (?, ?)",
                (delivery_id, time.time()),
            )
            if receipt.rowcount != 1:
                return False
            connection.execute(
                """
                INSERT INTO webhook_events (
                    delivery_id, payload_json, status, next_attempt_at, created_at
                ) VALUES (?, ?, 'pending', 0, ?)
                """,
                (delivery_id, serialized, time.time()),
            )
        return True

    def claim_webhooks(self, limit: int = 20) -> list[QueuedWebhook]:
        now = time.time()
        claimed: list[QueuedWebhook] = []
        with self._guard, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT delivery_id, payload_json, attempts
                FROM webhook_events
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY created_at
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE webhook_events SET status = 'processing' WHERE delivery_id = ?",
                    (row["delivery_id"],),
                )
                value: object = json.loads(str(row["payload_json"]))
                if isinstance(value, dict):
                    claimed.append(
                        QueuedWebhook(
                            delivery_id=str(row["delivery_id"]),
                            payload=cast(dict[str, Any], value),
                            attempts=int(row["attempts"]),
                        )
                    )
        return claimed

    def complete_webhook(self, delivery_id: str) -> None:
        with self._guard, self._connect() as connection:
            connection.execute(
                "DELETE FROM webhook_events WHERE delivery_id = ?",
                (delivery_id,),
            )

    def retry_webhook(
        self,
        delivery_id: str,
        error: str,
        attempts: int,
        retry_after: float | None = None,
    ) -> None:
        retry_count = attempts + 1
        if retry_count >= 10:
            status = "failed"
            next_attempt_at = 0.0
        else:
            status = "pending"
            backoff = min(300.0, 2.0**retry_count)
            delay = max(backoff, min(86400.0, retry_after or 0.0))
            next_attempt_at = time.time() + delay
        with self._guard, self._connect() as connection:
            connection.execute(
                """
                UPDATE webhook_events
                SET status = ?, attempts = ?, next_attempt_at = ?, last_error = ?
                WHERE delivery_id = ?
                """,
                (status, retry_count, next_attempt_at, error[:2000], delivery_id),
            )

    def recover_processing_webhooks(self) -> None:
        with self._guard, self._connect() as connection:
            connection.execute(
                "UPDATE webhook_events SET status = 'pending' WHERE status = 'processing'"
            )


def _installation_from_row(row: sqlite3.Row) -> LinearInstallation:
    raw_scope: object = json.loads(str(row["scope_json"]))
    scope = (
        tuple(str(item) for item in cast(list[object], raw_scope))
        if isinstance(raw_scope, list)
        else ()
    )
    return LinearInstallation(
        organization_id=str(row["organization_id"]),
        oauth_client_id=str(row["oauth_client_id"]),
        app_user_id=str(row["app_user_id"]),
        access_token=str(row["access_token"]),
        refresh_token=str(row["refresh_token"]),
        expires_at=float(row["expires_at"]),
        scope=scope,
        organization_name=str(row["organization_name"]),
        authorized_at=float(row["authorized_at"]),
    )


def local_state_present(_section: Any) -> bool:
    """Report OAuth installation state without importing the channel runtime."""
    path = get_config_path().parent / "linear" / "state.sqlite3"
    if not path.is_file():
        return False
    try:
        return LinearStateStore(path).has_installations()
    except (OSError, sqlite3.Error):
        return False
