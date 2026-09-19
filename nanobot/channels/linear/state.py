"""Durable installation and webhook state owned by the Linear channel."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
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

    def save_installation(self, installation: LinearInstallation) -> None:
        with self._guard, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO installations (
                    organization_id, oauth_client_id, app_user_id, access_token, refresh_token,
                    expires_at, scope_json, organization_name, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id) DO UPDATE SET
                    oauth_client_id=excluded.oauth_client_id,
                    app_user_id=excluded.app_user_id,
                    access_token=excluded.access_token,
                    refresh_token=excluded.refresh_token,
                    expires_at=excluded.expires_at,
                    scope_json=excluded.scope_json,
                    organization_name=excluded.organization_name,
                    updated_at=excluded.updated_at
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
                    time.time(),
                ),
            )

    def installation(self, organization_id: str) -> LinearInstallation | None:
        with self._guard, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM installations WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
        return _installation_from_row(row) if row is not None else None

    def delete_installation(self, organization_id: str) -> None:
        with self._guard, self._connect() as connection:
            connection.execute(
                "DELETE FROM installations WHERE organization_id = ?",
                (organization_id,),
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
