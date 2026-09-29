"""Transactional SQLite storage for private conversation state."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from nanobot.providers.base import ProviderConversationState
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import (
    Session,
    SessionInfo,
    SessionMetadataPayload,
    SessionPayload,
    message_preview_text,
    metadata_title,
)

_SCHEMA_VERSION = 1
_CHECKPOINT = "runtime_checkpoint"
_INPUTS = ("pending_user_followups",)
_T = TypeVar("_T")


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _object(value: str) -> dict[str, Any]:
    parsed: object = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("stored session record must be an object")
    return cast(dict[str, Any], parsed)


class SessionConflictError(RuntimeError):
    """A command refers to a replaced session or obsolete history."""


class SqliteSessionStore:
    """Synchronous repository; runtime callers use the session state's worker.

    Nested repository operations share a transaction. Every outer repository
    command closes its connection before returning to its caller.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self.path = sessions_dir / "sessions.sqlite3"
        self._local = threading.local()

    def run_write(self, operation: Callable[[], _T]) -> _T:
        """Run one repository command inside a write transaction."""
        with self.transaction():
            return operation()

    def run_read(self, operation: Callable[[], _T]) -> _T:
        """Run one repository command against a consistent read snapshot."""
        with self.transaction(write=False):
            return operation()

    @contextmanager
    def transaction(self, *, write: bool = True) -> Generator[sqlite3.Connection, None, None]:
        current: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if current is not None:
            yield current
            return
        if self.path.is_symlink():
            raise RuntimeError("session database must not be a symlink")
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
        except BaseException:
            connection.close()
            raise
        self._local.connection = connection
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            self._local.connection = None
            connection.close()

    def initialize(self, workspace: Path) -> None:
        """Create the schema and import legacy sessions in one atomic transaction."""
        # WAL is persistent and must be enabled outside a transaction.
        if self.path.is_symlink():
            raise RuntimeError("session database must not be a symlink")
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        finally:
            connection.close()
        with suppress(OSError):
            os.chmod(self.path, 0o600)
        with self.transaction() as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, _SCHEMA_VERSION):
                raise RuntimeError(f"unsupported session database schema: {version}")
            for statement in (
                "CREATE TABLE IF NOT EXISTS storage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                """CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL, provider_state TEXT, last_archived INTEGER NOT NULL,
                    revision INTEGER NOT NULL, generation TEXT NOT NULL,
                    title TEXT NOT NULL, preview TEXT NOT NULL, visible_updated_at TEXT
                )""",
                """CREATE TABLE IF NOT EXISTS messages (
                    session_key TEXT NOT NULL REFERENCES sessions(key) ON DELETE CASCADE,
                    position INTEGER NOT NULL, record TEXT NOT NULL,
                    PRIMARY KEY (session_key, position)
                )""",
                """CREATE TABLE IF NOT EXISTS checkpoints (
                    session_key TEXT PRIMARY KEY REFERENCES sessions(key) ON DELETE CASCADE,
                    record TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS pending_inputs (
                    session_key TEXT NOT NULL REFERENCES sessions(key) ON DELETE CASCADE,
                    kind TEXT NOT NULL, position INTEGER NOT NULL, record TEXT NOT NULL,
                    PRIMARY KEY (session_key, kind, position)
                )""",
                "CREATE INDEX IF NOT EXISTS sessions_updated ON sessions(updated_at DESC)",
            ):
                db.execute(statement)
            marker = db.execute(
                "SELECT value FROM storage_meta WHERE key='jsonl_import'"
            ).fetchone()
            if marker is None:
                from nanobot.session.jsonl_migration import migrate_jsonl

                migrate_jsonl(self, workspace)
                db.execute("INSERT INTO storage_meta VALUES ('jsonl_import', 'complete')")
            elif marker[0] != "complete":
                raise RuntimeError(
                    f"invalid JSONL migration marker in {self.path}: {marker[0]!r}; "
                    "restore a valid database backup or repair the marker explicitly"
                )
            db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def _metadata(self, db: sqlite3.Connection, key: str, raw: str) -> dict[str, Any]:
        metadata = _object(raw)
        row = db.execute("SELECT record FROM checkpoints WHERE session_key=?", (key,)).fetchone()
        if row is not None:
            metadata[_CHECKPOINT] = _object(row[0])
        for kind in _INPUTS:
            values = [
                _object(row[0]) for row in db.execute(
                    "SELECT record FROM pending_inputs WHERE session_key=? AND kind=? ORDER BY position",
                    (key, kind),
                )
            ]
            if values:
                metadata[kind] = values
        return metadata

    def load(self, key: str, *, history: bool = True) -> Session | None:
        with self.transaction(write=False) as db:
            row = db.execute("SELECT * FROM sessions WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            session = Session(
                key=key,
                messages=[_object(item[0]) for item in db.execute(
                    "SELECT record FROM messages WHERE session_key=? ORDER BY position", (key,),
                )] if history else [],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=self._metadata(db, key, row["metadata"]),
                last_consolidated=row["last_archived"],
                provider_state=ProviderConversationState.from_private_record(
                    _object(row["provider_state"])
                ) if row["provider_state"] is not None else None,
                revision=row["revision"], generation=row["generation"], persisted=True,
            )
            if not history:
                # A header carries the real offset even though history was not requested.
                session.last_archived = row["last_archived"]
            return session

    @staticmethod
    def _write_metadata(db: sqlite3.Connection, key: str, values: dict[str, Any], *, bump_revision: bool = True) -> None:
        metadata = dict(values)
        checkpoint = metadata.pop(_CHECKPOINT, None)
        if checkpoint is None:
            db.execute("DELETE FROM checkpoints WHERE session_key=?", (key,))
        else:
            db.execute(
                "INSERT INTO checkpoints VALUES (?, ?) ON CONFLICT(session_key) DO UPDATE SET record=excluded.record",
                (key, _encode(checkpoint)),
            )
        for kind in _INPUTS:
            inputs = metadata.pop(kind, [])
            if not isinstance(inputs, list):
                raise ValueError(f"{kind} must be a list")
            db.execute("DELETE FROM pending_inputs WHERE session_key=? AND kind=?", (key, kind))
            db.executemany("INSERT INTO pending_inputs VALUES (?, ?, ?, ?)", [
                (key, kind, position, _encode(record))
                for position, record in enumerate(cast(list[object], inputs))
            ])
        db.execute("UPDATE sessions SET metadata=?, title=?, revision=revision+? WHERE key=?", (
            _encode(metadata), metadata_title(metadata), int(bump_revision), key,
        ))

    def save(self, session: Session, *, message_start: int = 0) -> None:
        """Commit history, optionally skipping a prefix verified at this revision."""
        if not 0 <= message_start <= len(session.messages):
            raise ValueError("invalid message suffix boundary")
        records = [_encode(message) for message in session.messages[message_start:]]
        provider = _encode(session.provider_state.to_private_record()) if session.provider_state else None
        preview = ""
        fallback = ""
        scanned_chars = 0
        for message in session.messages[:200]:
            scanned_chars += len(_encode(message)) + 1
            if scanned_chars > 1_000_000:
                break
            if is_hidden_history_message(message):
                continue
            text = message_preview_text(message)
            if message.get("role") == "user" and text:
                preview = text
                break
            if message.get("role") == "assistant" and not fallback:
                fallback = text
        preview = preview or fallback
        last_visible = next((m["timestamp"] for m in reversed(session.messages)
                             if m.get("timestamp") and not is_hidden_history_message(m)
                             and m.get("role") in {"user", "assistant"}), None)
        with self.transaction() as db:
            row = db.execute("SELECT revision, generation FROM sessions WHERE key=?", (session.key,)).fetchone()
            if row is None:
                if session.persisted:
                    raise SessionConflictError("session was deleted")
                if message_start:
                    raise ValueError("a new session must include its full history")
                db.execute("INSERT INTO sessions VALUES (?, ?, ?, '{}', NULL, 0, 0, ?, '', '', NULL)", (
                    session.key, session.created_at.isoformat(), session.updated_at.isoformat(), session.generation,
                ))
            elif row[0] != session.revision or row[1] != session.generation:
                raise SessionConflictError("session history changed")
            db.execute("UPDATE sessions SET updated_at=?, provider_state=?, last_archived=?, revision=revision+1, preview=?, visible_updated_at=? WHERE key=?", (
                session.updated_at.isoformat(), provider, session.last_archived,
                preview, last_visible, session.key,
            ))
            # Unchanged message rows do not generate writes. Appends only write the suffix.
            db.executemany("""INSERT INTO messages VALUES (?, ?, ?)
                ON CONFLICT(session_key, position) DO UPDATE SET record=excluded.record
                WHERE messages.record != excluded.record""", [
                    (session.key, position, record)
                    for position, record in enumerate(records, message_start)
                ])
            db.execute("DELETE FROM messages WHERE session_key=? AND position>=?", (session.key, len(session.messages)))
            self._write_metadata(db, session.key, session.metadata, bump_revision=False)
        session.revision += 1
        session.persisted = True

    def save_runtime_checkpoint(self, session: Session) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT generation FROM sessions WHERE key=?", (session.key,)).fetchone()
            if row is None or row[0] != session.generation:
                raise SessionConflictError("checkpoint belongs to a replaced session")
            metadata = self.read_metadata(session.key)
            assert metadata is not None
            values = metadata["metadata"]
            if _CHECKPOINT in session.metadata:
                values[_CHECKPOINT] = session.metadata[_CHECKPOINT]
            else:
                values.pop(_CHECKPOINT, None)
            self._write_metadata(db, session.key, values)
            session.revision += 1
            db.execute("UPDATE sessions SET provider_state=? WHERE key=?", (
                _encode(session.provider_state.to_private_record()) if session.provider_state else None,
                session.key,
            ))

    def update_metadata(self, key: str, updates: dict[str, Any]) -> bool:
        with self.transaction() as db:
            payload = self.read_metadata(key)
            if payload is None:
                return False
            self._write_metadata(db, key, {**payload["metadata"], **updates})
            return True

    def replace_metadata(
        self, key: str, metadata: dict[str, Any], *, updated_at: datetime | None = None,
    ) -> None:
        with self.transaction() as db:
            self._write_metadata(db, key, metadata)
            if updated_at is not None:
                db.execute("UPDATE sessions SET updated_at=? WHERE key=?", (updated_at.isoformat(), key))

    def read_metadata(self, key: str) -> SessionMetadataPayload | None:
        with self.transaction(write=False) as db:
            row = db.execute("SELECT created_at, updated_at, metadata FROM sessions WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            return {"key": key, "created_at": row[0], "updated_at": row[1],
                    "metadata": self._metadata(db, key, row[2])}

    def read(self, key: str) -> SessionPayload | None:
        session = self.load(key)
        if session is None:
            return None
        return {"key": key, "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata, "messages": session.messages}

    def delete(self, key: str) -> bool:
        with self.transaction() as db:
            return db.execute("DELETE FROM sessions WHERE key=?", (key,)).rowcount > 0

    def list_sessions(self) -> list[SessionInfo]:
        with self.transaction(write=False) as db:
            return [SessionInfo(key=row[0], created_at=row[1], updated_at=row[2],
                                title=row[3], preview=row[4], path=str(self.path))
                    for row in db.execute("SELECT key, created_at, updated_at, title, preview FROM sessions ORDER BY updated_at DESC")]

    def list_metadata(self) -> list[dict[str, Any]]:
        with self.transaction(write=False) as db:
            return [{"key": row["key"], "created_at": row["created_at"],
                     "updated_at": row["updated_at"], "title": row["title"],
                     "preview": row["preview"], "visible_updated_at": row["visible_updated_at"],
                     "path": str(self.path), "metadata": _object(row["metadata"])}
                    for row in db.execute("SELECT key, created_at, updated_at, title, preview, visible_updated_at, metadata FROM sessions ORDER BY updated_at DESC")]

    def snapshot_sessions(self) -> list[Session]:
        """Return one consistent, detached snapshot for explicit export."""
        with self.transaction(write=False):
            sessions: list[Session] = []
            for row in self.list_sessions():
                session = self.load(row["key"])
                assert session is not None
                sessions.append(session)
            return sessions
