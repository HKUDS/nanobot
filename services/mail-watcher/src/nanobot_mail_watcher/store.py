"""Crash-recoverable SQLite queue and audit log for mailbox events."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, cast

from nanobot_mail_watcher.models import MailEvent, QueuedMailEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    account TEXT NOT NULL,
    mailbox TEXT NOT NULL,
    uid_validity TEXT NOT NULL,
    uid TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'retry', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL,
    claimed_at REAL,
    claim_token TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_error TEXT,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_mail_events_claim
    ON mail_events(status, available_at, id);
CREATE TABLE IF NOT EXISTS mail_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    recorded_at REAL NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES mail_events(id)
);
CREATE INDEX IF NOT EXISTS idx_mail_audit_event ON mail_audit(event_id, id);
"""


class LostLeaseError(RuntimeError):
    """Raised when a worker tries to mutate an event it no longer owns."""


class MailEventStore:
    """SQLite-backed queue safe for concurrent Carillon and worker processes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._prepare()

    def _prepare(self) -> None:
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            if not parent_existed:
                os.chmod(self.path.parent, 0o700)
            elif self.path.parent.stat().st_mode & 0o077:
                raise ValueError(
                    f"mail state directory is accessible by other users: {self.path.parent}"
                )
            if not self.path.exists():
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            elif self.path.stat().st_mode & 0o077:
                raise ValueError(f"mail database is accessible by other users: {self.path}")
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(mail_events)").fetchall()
            }
            if "claim_token" not in columns:
                connection.execute("ALTER TABLE mail_events ADD COLUMN claim_token TEXT")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def enqueue(self, event: MailEvent, *, now: float | None = None) -> tuple[int, bool]:
        """Insert an event once, returning its row ID and whether it was newly created."""
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO mail_events (
                        event_key, account, mailbox, uid_validity, uid, metadata_json,
                        status, attempts, available_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (
                        event.event_key,
                        event.account,
                        event.mailbox,
                        event.uid_validity,
                        event.uid,
                        _encode(event.metadata),
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                created = cursor.rowcount == 1
                row = connection.execute(
                    "SELECT id FROM mail_events WHERE event_key = ?", (event.event_key,)
                ).fetchone()
                if row is None:  # pragma: no cover
                    raise RuntimeError("queued event disappeared")
                event_id = int(row["id"])
                if created:
                    _append_audit(connection, event_id, "enqueued", {}, timestamp)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return event_id, created

    def recover_stale(
        self,
        stale_after_seconds: float,
        *,
        max_attempts: int,
        now: float | None = None,
    ) -> int:
        """Recover abandoned claims without exceeding the configured attempt budget."""
        timestamp = time.time() if now is None else now
        cutoff = timestamp - stale_after_seconds
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT id, attempts FROM mail_events
                    WHERE status = 'processing' AND claimed_at IS NOT NULL AND claimed_at <= ?
                    """,
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    event_id = int(row["id"])
                    exhausted = int(row["attempts"]) >= max_attempts
                    status = "failed" if exhausted else "retry"
                    error = (
                        "attempt budget exhausted after interrupted processing"
                        if exhausted
                        else "recovered after interrupted processing"
                    )
                    connection.execute(
                        """
                        UPDATE mail_events
                        SET status = ?, available_at = ?, claimed_at = NULL, claim_token = NULL,
                            updated_at = ?, last_error = ? WHERE id = ?
                        """,
                        (status, timestamp, timestamp, error, event_id),
                    )
                    _append_audit(
                        connection,
                        event_id,
                        "failed" if exhausted else "recovered",
                        {"reason": "stale_processing"},
                        timestamp,
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return len(rows)

    def claim(self, *, limit: int = 1, now: float | None = None) -> list[QueuedMailEvent]:
        """Atomically claim available events and increment their attempt counters."""
        if limit < 1:
            return []
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT id FROM mail_events
                    WHERE status IN ('pending', 'retry') AND available_at <= ?
                    ORDER BY available_at, id LIMIT ?
                    """,
                    (timestamp, limit),
                ).fetchall()
                ids = [int(row["id"]) for row in rows]
                if not ids:
                    connection.commit()
                    return []
                claimed_rows: list[sqlite3.Row] = []
                for event_id in ids:
                    claim_token = uuid.uuid4().hex
                    connection.execute(
                        """
                        UPDATE mail_events
                        SET status = 'processing', attempts = attempts + 1,
                            claimed_at = ?, claim_token = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (timestamp, claim_token, timestamp, event_id),
                    )
                    claimed = connection.execute(
                        "SELECT * FROM mail_events WHERE id = ?", (event_id,)
                    ).fetchone()
                    if claimed is None:  # pragma: no cover
                        raise RuntimeError("claimed mail event disappeared")
                    claimed_rows.append(claimed)
                    _append_audit(connection, event_id, "claimed", {}, timestamp)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return [_row_to_event(row) for row in claimed_rows]

    def resolve_uid_validity(
        self,
        queued: QueuedMailEvent,
        uid_validity: str,
        *,
        now: float | None = None,
    ) -> int | None:
        """Promote an unknown identity; return an existing row ID when duplicate."""
        if queued.event.uid_validity_known:
            return None
        resolved = MailEvent(
            account=queued.event.account,
            mailbox=queued.event.mailbox,
            uid=queued.event.uid,
            uid_validity=uid_validity,
            metadata=queued.event.metadata,
        )
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT id FROM mail_events WHERE event_key = ? AND id != ?",
                    (resolved.event_key, queued.id),
                ).fetchone()
                if existing is not None:
                    duplicate_id = int(existing["id"])
                    result = {"duplicate_of": duplicate_id, "uid_validity": uid_validity}
                    changed = connection.execute(
                        """
                        UPDATE mail_events
                        SET status = 'done', claimed_at = NULL, claim_token = NULL, updated_at = ?,
                            result_json = ?, last_error = NULL
                        WHERE id = ? AND status = 'processing' AND claim_token = ?
                        """,
                        (timestamp, _encode(result), queued.id, queued.claim_token),
                    ).rowcount
                    _require_lease(changed)
                    _append_audit(connection, queued.id, "deduplicated", result, timestamp)
                    connection.commit()
                    return duplicate_id
                changed = connection.execute(
                    """
                    UPDATE mail_events SET event_key = ?, uid_validity = ?, updated_at = ?
                    WHERE id = ? AND status = 'processing' AND claim_token = ?
                    """,
                    (
                        resolved.event_key,
                        uid_validity,
                        timestamp,
                        queued.id,
                        queued.claim_token,
                    ),
                ).rowcount
                _require_lease(changed)
                _append_audit(
                    connection,
                    queued.id,
                    "uid_validity_resolved",
                    {"uid_validity": uid_validity},
                    timestamp,
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return None

    def renew_lease(
        self, event_id: int, claim_token: str, *, now: float | None = None
    ) -> None:
        """Refresh a claim immediately before another bounded external operation."""
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            changed = connection.execute(
                """
                UPDATE mail_events SET claimed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'processing' AND claim_token = ?
                """,
                (timestamp, timestamp, event_id, claim_token),
            ).rowcount
        _require_lease(changed)

    def record_decision(
        self,
        event_id: int,
        claim_token: str,
        decision: dict[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """
                    UPDATE mail_events SET result_json = ?, updated_at = ?
                    WHERE id = ? AND status = 'processing' AND claim_token = ?
                    """,
                    (_encode({"decision": decision}), timestamp, event_id, claim_token),
                ).rowcount
                _require_lease(changed)
                _append_audit(connection, event_id, "decision", decision, timestamp)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def record_action_started(
        self,
        event_id: int,
        claim_token: str,
        decision: dict[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        """Durably mark the point after which repeating MOVE would be unsafe."""
        timestamp = time.time() if now is None else now
        result = {"decision": decision, "action_started": True}
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """
                    UPDATE mail_events SET result_json = ?, claimed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'processing' AND claim_token = ?
                    """,
                    (_encode(result), timestamp, timestamp, event_id, claim_token),
                ).rowcount
                _require_lease(changed)
                _append_audit(connection, event_id, "move_started", decision, timestamp)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def complete(
        self,
        event_id: int,
        claim_token: str,
        result: dict[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """
                    UPDATE mail_events
                    SET status = 'done', claimed_at = NULL, claim_token = NULL,
                        updated_at = ?, result_json = ?, last_error = NULL
                    WHERE id = ? AND status = 'processing' AND claim_token = ?
                    """,
                    (timestamp, _encode(result), event_id, claim_token),
                ).rowcount
                _require_lease(changed)
                _append_audit(connection, event_id, "completed", result, timestamp)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def fail(
        self,
        event_id: int,
        claim_token: str,
        error: str,
        *,
        max_attempts: int,
        retry_base_seconds: float,
        permanent: bool = False,
        now: float | None = None,
    ) -> bool:
        """Retry or fail an event; return whether it was scheduled again."""
        timestamp = time.time() if now is None else now
        clean_error = _bounded_error(error)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT attempts FROM mail_events
                    WHERE id = ? AND status = 'processing' AND claim_token = ?
                    """,
                    (event_id, claim_token),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return False
                attempts = int(row["attempts"])
                retry = not permanent and attempts < max_attempts
                if retry:
                    delay = min(retry_base_seconds * (2 ** max(0, attempts - 1)), 3600.0)
                    connection.execute(
                        """
                        UPDATE mail_events
                        SET status = 'retry', available_at = ?, claimed_at = NULL,
                            claim_token = NULL, updated_at = ?, last_error = ? WHERE id = ?
                        """,
                        (timestamp + delay, timestamp, clean_error, event_id),
                    )
                    _append_audit(
                        connection,
                        event_id,
                        "retry_scheduled",
                        {"error": clean_error, "retry_in": delay},
                        timestamp,
                    )
                else:
                    connection.execute(
                        """
                        UPDATE mail_events
                        SET status = 'failed', claimed_at = NULL, claim_token = NULL,
                            updated_at = ?, last_error = ? WHERE id = ?
                        """,
                        (timestamp, clean_error, event_id),
                    )
                    _append_audit(
                        connection, event_id, "failed", {"error": clean_error}, timestamp
                    )
                connection.commit()
                return retry
            except BaseException:
                connection.rollback()
                raise

    def counts(self) -> dict[str, int]:
        result = {status: 0 for status in ("pending", "processing", "retry", "done", "failed")}
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM mail_events GROUP BY status"
            ).fetchall()
        for row in rows:
            result[str(row["status"])] = int(row["count"])
        return result

    def audit(self, event_id: int) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT recorded_at, action, details_json FROM mail_audit
                WHERE event_id = ? ORDER BY id
                """,
                (event_id,),
            ).fetchall()
        return [
            {
                "recorded_at": float(row["recorded_at"]),
                "action": str(row["action"]),
                "details": _decode_dict(str(row["details_json"])),
            }
            for row in rows
        ]


def _append_audit(
    connection: sqlite3.Connection,
    event_id: int,
    action: str,
    details: dict[str, Any],
    timestamp: float,
) -> None:
    connection.execute(
        """
        INSERT INTO mail_audit(event_id, recorded_at, action, details_json)
        VALUES (?, ?, ?, ?)
        """,
        (event_id, timestamp, action, _encode(details)),
    )


def _row_to_event(row: sqlite3.Row) -> QueuedMailEvent:
    return QueuedMailEvent(
        id=int(row["id"]),
        event=MailEvent(
            account=str(row["account"]),
            mailbox=str(row["mailbox"]),
            uid=str(row["uid"]),
            uid_validity=str(row["uid_validity"]),
            metadata=_decode_dict(str(row["metadata_json"])),
        ),
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        created_at=float(row["created_at"]),
        available_at=float(row["available_at"]),
        claim_token=str(row["claim_token"]),
        action_started=_action_started(row["result_json"]),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
    )


def _encode(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_dict(value: str) -> dict[str, Any]:
    decoded = cast(object, json.loads(value))
    if not isinstance(decoded, dict):
        raise ValueError("persisted mail event JSON is not an object")
    return cast(dict[str, Any], decoded)


def _bounded_error(error: str) -> str:
    return (" ".join(error.split())[:2000] or "mail processing failed")


def _action_started(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(decoded, dict) and decoded.get("action_started") is True


def _require_lease(changed: int) -> None:
    if changed != 1:
        raise LostLeaseError("mail event lease is no longer owned by this worker")
