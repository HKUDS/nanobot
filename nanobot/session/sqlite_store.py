from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import CancelledError
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from nanobot.providers.base import ProviderConversationState
from nanobot.session.display_history import HistoryFact, HistoryImport, HistoryKind, HistoryReader
from nanobot.session.history_graph import history_record_size
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import (
    Session,
    SessionHistoryPayload,
    SessionInfo,
    SessionMetadataPayload,
    SessionPayload,
    fork_session,
    message_preview_text,
    metadata_title,
)
from nanobot.session.model_selection import SESSION_MODEL_KEYS, SessionModelPreset
from nanobot.session.summary import is_summary_checkpoint
from nanobot.session.types import CONVERSATION, PARENT_SESSION_KEY, SESSION_TYPE_KEY

_CHECKPOINT = "runtime_checkpoint"
_INPUTS = ("pending_user_followups",)
_T = TypeVar("_T")

# The expression below defines the v6 partial index and must stay stable for upgrades.
_SUBAGENT_ORIGIN = "origin_turn_id"
_SUBAGENT_PARENT = f"json_extract(metadata, '$.{PARENT_SESSION_KEY}')"
_SUBAGENT_ORIGIN_FILTER = (
    f"json_extract(metadata, '$.{SESSION_TYPE_KEY}')='subagent' "
    f"AND json_type(metadata, '$.{PARENT_SESSION_KEY}')='text' "
    f"AND json_type(metadata, '$.subagent_task.{_SUBAGENT_ORIGIN}')='text'"
)

# Field names above are fixed by the schema; all caller-supplied values are bound.
_SUBAGENT_METADATA_QUERY = f"""SELECT key, created_at, updated_at, metadata FROM sessions
    WHERE {_SUBAGENT_ORIGIN_FILTER}
    AND {_SUBAGENT_PARENT}=?
    AND json_extract(metadata, '$.subagent_task.{_SUBAGENT_ORIGIN}') IN (SELECT value FROM json_each(?))"""


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _object(value: str) -> dict[str, Any]:
    parsed: object = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("stored session record must be an object")
    return cast(dict[str, Any], parsed)


def _create_schema_v1(db: sqlite3.Connection) -> None:
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


def _create_schema_v2(db: sqlite3.Connection) -> None:
    for statement in (
        """CREATE TABLE history_heads (
            session_key TEXT PRIMARY KEY REFERENCES sessions(key) ON DELETE CASCADE,
            revision INTEGER NOT NULL DEFAULT 0,
            updated_at_ms INTEGER NOT NULL DEFAULT 0,
            preview TEXT NOT NULL DEFAULT '', user_preview TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE history_turns (
            session_key TEXT NOT NULL REFERENCES sessions(key) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL, record_count INTEGER NOT NULL,
            byte_count INTEGER NOT NULL, user_count INTEGER NOT NULL,
            completed INTEGER NOT NULL,
            PRIMARY KEY (session_key, ordinal)
        )""",
        """CREATE TABLE history_entries (
            session_key TEXT NOT NULL, turn_ordinal INTEGER NOT NULL,
            position INTEGER NOT NULL, kind TEXT NOT NULL, record TEXT NOT NULL,
            PRIMARY KEY (session_key, turn_ordinal, position),
            FOREIGN KEY (session_key, turn_ordinal)
                REFERENCES history_turns(session_key, ordinal) ON DELETE CASCADE
        )""",
    ):
        db.execute(statement)


def _create_schema_v3(db: sqlite3.Connection) -> None:
    # Empty chats can be archived before their first persisted message.
    db.execute("""CREATE TABLE session_archives (
        key TEXT PRIMARY KEY, archived_at TEXT NOT NULL
    )""")


def _create_schema_v4(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE session_archives_v4 (
        key TEXT PRIMARY KEY REFERENCES sessions(key)
            ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
        archived_at TEXT NOT NULL
    )""")
    db.execute("""INSERT INTO session_archives_v4 (key, archived_at)
        SELECT archives.key, archives.archived_at FROM session_archives AS archives
        JOIN sessions ON sessions.key = archives.key""")
    db.execute("DROP TABLE session_archives")
    db.execute("ALTER TABLE session_archives_v4 RENAME TO session_archives")


def _create_schema_v5(db: sqlite3.Connection) -> None:
    db.execute("""CREATE UNIQUE INDEX history_input_identity ON history_entries (
        session_key, json_extract(record, '$.content.input_id')
    ) WHERE kind='input'""")


def _create_schema_v6(db: sqlite3.Connection) -> None:
    db.execute(f"""CREATE INDEX sessions_subagent_{_SUBAGENT_ORIGIN} ON sessions (
        {_SUBAGENT_PARENT}, json_extract(metadata, '$.subagent_task.{_SUBAGENT_ORIGIN}')
    ) WHERE {_SUBAGENT_ORIGIN_FILTER}""")


# Entries upgrade version N to N+1. Preserve released entries and append upgrades.
_SCHEMA_MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _create_schema_v1, _create_schema_v2, _create_schema_v3, _create_schema_v4, _create_schema_v5,
    _create_schema_v6,
)


def _schema_version(db: sqlite3.Connection) -> int:
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if not 0 <= version <= len(_SCHEMA_MIGRATIONS):
        raise RuntimeError(f"unsupported session database schema: {version}")
    return version


class SessionConflictError(RuntimeError):
    """A command refers to a replaced session or obsolete history."""


class SqliteSessionStore:
    """Synchronous repository; runtime callers use the session state's worker.

    Nested repository operations share a transaction. Runtime worker threads
    retain their own connections until their state owner drains and closes;
    administrative calls close each connection after their transaction.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self.path = sessions_dir / "sessions.sqlite3"
        self._local = threading.local()

    def run_write(self, operation: Callable[[], _T]) -> _T:
        """Run one repository command inside a write transaction."""
        with self.transaction():
            return operation()

    def run_read(
        self, operation: Callable[[], _T], *, cancelled: threading.Event | None = None,
    ) -> _T:
        """Run one repository command against a consistent read snapshot."""
        with self.transaction(write=False) as db:
            if cancelled is None:
                return operation()
            if cancelled.is_set():
                raise CancelledError()
            # Interrupt long SQLite work as well as the Python-level row scans.
            db.set_progress_handler(cancelled.is_set, 1000)
            try:
                return operation()
            except sqlite3.OperationalError:
                if cancelled.is_set():
                    raise CancelledError() from None
                raise
            finally:
                db.set_progress_handler(None, 0)

    def run_read_batch(self, operation: Callable[[], _T]) -> _T:
        """Reuse one connection across independent short read transactions."""
        if getattr(self._local, "connection", None) is not None or getattr(self._local, "read_batch", None) is not None:
            return operation()
        connection: sqlite3.Connection | None = getattr(self._local, "worker_connection", None)
        owned = connection is None
        if connection is None:
            connection = self._open_connection()
        self._local.read_batch = connection
        try:
            return operation()
        finally:
            self._local.read_batch = None
            if owned:
                connection.close()

    def _open_connection(self, *, worker: bool = False) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise RuntimeError("session database must not be a symlink")
        connection = sqlite3.connect(
            self.path, timeout=5, isolation_level=None, check_same_thread=not worker,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    def worker_connection(self) -> sqlite3.Connection:
        """Retain this worker's connection; its owner closes it after the worker exits."""
        connection: sqlite3.Connection | None = getattr(self._local, "worker_connection", None)
        if connection is None:
            connection = self._open_connection(worker=True)
            self._local.worker_connection = connection
        return connection

    @contextmanager
    def transaction(self, *, write: bool = True) -> Generator[sqlite3.Connection, None, None]:
        current: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if current is not None:
            yield current
            return
        if self.path.is_symlink():
            raise RuntimeError("session database must not be a symlink")
        connection: sqlite3.Connection | None = getattr(self._local, "read_batch", None)
        if connection is None:
            connection = getattr(self._local, "worker_connection", None)
        owned = connection is None
        if connection is None:
            connection = self._open_connection()
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
            if owned:
                connection.close()

    # TODO(0.5.0): Remove JSONL import and backup finalization; retain throughout 0.4.x.
    def initialize(self, workspace: Path) -> None:
        """Upgrade the schema and import legacy sessions in one atomic transaction."""
        workspace = workspace.expanduser().resolve(strict=False)
        # WAL is persistent and must be enabled outside a transaction.
        if self.path.is_symlink():
            raise RuntimeError("session database must not be a symlink")
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            # Reject newer databases before changing their persistent settings.
            _schema_version(connection)
            try:
                connection.execute("SELECT json_extract('{}', '$'), json_type('{}')")
            except sqlite3.OperationalError as exc:
                raise RuntimeError(
                    "session storage requires SQLite JSON support; use a Python build "
                    "linked to SQLite with JSON enabled"
                ) from exc
            connection.execute("PRAGMA journal_mode = WAL")
        finally:
            connection.close()
        with suppress(OSError):
            os.chmod(self.path, 0o600)
        with self.transaction() as db:
            # Recheck under the write lock in case another startup upgraded first.
            version = _schema_version(db)
            for target, migrate in enumerate(_SCHEMA_MIGRATIONS[version:], start=version + 1):
                migrate(db)
                db.execute(f"PRAGMA user_version = {target}")
            marker = db.execute(
                "SELECT value FROM storage_meta WHERE key='jsonl_import'"
            ).fetchone()
            if marker is None:
                from nanobot.session.jsonl_migration import migrate_jsonl

                migrate_jsonl(self, workspace)
                db.execute("INSERT INTO storage_meta (key, value) VALUES ('jsonl_import', 'complete')")
            elif marker[0] != "complete":
                raise RuntimeError(
                    f"invalid JSONL migration marker in {self.path}: {marker[0]!r}; "
                    "restore a valid database backup or repair the marker explicitly"
                )
        from nanobot.session.jsonl_migration import finish_workspace_migration

        finish_workspace_migration(self, workspace)

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

    def has_unarchived_messages(self, key: str) -> bool:
        """Check the indexed suffix without loading the archived transcript."""
        with self.transaction(write=False) as db:
            for row in db.execute(
                """SELECT record FROM messages
                   WHERE session_key=? AND position >= (
                       SELECT last_archived FROM sessions WHERE key=?
                   ) ORDER BY position""",
                (key, key),
            ):
                message = _object(row[0])
                if not message.get("_command") and not is_summary_checkpoint(message):
                    return True
            return False

    @staticmethod
    def _write_metadata(db: sqlite3.Connection, key: str, values: dict[str, Any], *, bump_revision: bool = True) -> None:
        metadata = dict(values)
        checkpoint = metadata.pop(_CHECKPOINT, None)
        if checkpoint is None:
            db.execute("DELETE FROM checkpoints WHERE session_key=?", (key,))
        else:
            db.execute(
                "INSERT INTO checkpoints (session_key, record) VALUES (?, ?) ON CONFLICT(session_key) DO UPDATE SET record=excluded.record",
                (key, _encode(checkpoint)),
            )
        for kind in _INPUTS:
            inputs = metadata.pop(kind, [])
            if not isinstance(inputs, list):
                raise ValueError(f"{kind} must be a list")
            db.execute("DELETE FROM pending_inputs WHERE session_key=? AND kind=?", (key, kind))
            db.executemany("INSERT INTO pending_inputs (session_key, kind, position, record) VALUES (?, ?, ?, ?)", [
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
                db.execute("""INSERT INTO sessions (
                    key, created_at, updated_at, metadata, provider_state, last_archived,
                    revision, generation, title, preview, visible_updated_at
                ) VALUES (?, ?, ?, '{}', NULL, 0, 0, ?, '', '', NULL)""", (
                    session.key, session.created_at.isoformat(), session.updated_at.isoformat(), session.generation,
                ))
            elif row[0] != session.revision or row[1] != session.generation:
                raise SessionConflictError("session history changed")
            db.execute("UPDATE sessions SET updated_at=?, provider_state=?, last_archived=?, revision=revision+1, preview=?, visible_updated_at=? WHERE key=?", (
                session.updated_at.isoformat(), provider, session.last_archived,
                preview, last_visible, session.key,
            ))
            # Unchanged message rows do not generate writes. Appends only write the suffix.
            db.executemany("""INSERT INTO messages (session_key, position, record) VALUES (?, ?, ?)
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

    def rename_model_preset(self, old_name: str, new_name: str) -> list[str]:
        changed: list[str] = []
        with self.transaction():
            for row in self.list_metadata():
                metadata = row["metadata"]
                try:
                    selection = SessionModelPreset.from_metadata(metadata)
                except ValueError:
                    continue
                if selection.base_preset != old_name:
                    continue
                for key in SESSION_MODEL_KEYS:
                    metadata.pop(key, None)
                metadata.update(SessionModelPreset(new_name, selection.overrides).metadata_update())
                self.replace_metadata(row["key"], metadata)
                changed.append(row["key"])
        return changed

    def replace_metadata(
        self, key: str, metadata: dict[str, Any], *, updated_at: datetime | None = None,
    ) -> None:
        with self.transaction() as db:
            self._write_metadata(db, key, metadata)
            if updated_at is not None:
                db.execute("UPDATE sessions SET updated_at=? WHERE key=?", (updated_at.isoformat(), key))

    def read_version(self, key: str) -> tuple[str, int] | None:
        """Read the committed lifecycle and revision without decoding history or metadata."""
        with self.transaction(write=False) as db:
            row = db.execute("SELECT generation, revision FROM sessions WHERE key=?", (key,)).fetchone()
            return (str(row[0]), int(row[1])) if row is not None else None

    def read_metadata(self, key: str) -> SessionMetadataPayload | None:
        with self.transaction(write=False) as db:
            row = db.execute("SELECT created_at, updated_at, metadata FROM sessions WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            return {"key": key, "created_at": row[0], "updated_at": row[1],
                    "metadata": self._metadata(db, key, row[2])}

    def recovery_candidates(self, key_prefix: str) -> list[tuple[str, bool]]:
        """Return (key, unfinished display tail) in the same order as list_sessions.

        The turn and entry primary keys locate the last ordinal and its last
        decisive fact. Fork/telemetry facts do not settle activity. As in the
        transcript reader, an incomplete marker *anywhere in that ordinal*
        takes precedence, including on imported records. The append cursor's
        `completed` flag alone cannot answer either question.
        """
        with self.transaction(write=False) as db:
            rows = db.execute("""
                WITH scan AS (
                    SELECT s.key, s.updated_at, s.rowid AS tie,
                           json_type(s.metadata, '$.pending_user_turn')='true'
                           OR (json_extract(s.metadata, '$.webui_recovery.status')
                                   IN ('resuming', 'awaiting_user', 'failed')
                               AND json_type(s.metadata, '$.webui_recovery.recovery_id')='text')
                           OR EXISTS (SELECT 1 FROM checkpoints WHERE session_key=s.key)
                           OR EXISTS (SELECT 1 FROM pending_inputs WHERE session_key=s.key
                                      AND kind='pending_user_followups') AS journaled,
                           (SELECT CASE WHEN
                                (SELECT e.kind NOT IN ('input', 'answer', 'completion')
                                 FROM history_entries e WHERE e.session_key=t.session_key
                                 AND e.turn_ordinal=t.ordinal
                                 AND e.kind NOT IN ('fork_boundary', 'compaction', 'model_request')
                                 ORDER BY e.position DESC LIMIT 1)
                                THEN 1 ELSE EXISTS (
                                    SELECT 1 FROM history_entries e WHERE e.session_key=t.session_key
                                    AND e.turn_ordinal=t.ordinal
                                    AND json_type(e.record, '$.content.transcript_incomplete')='true'
                                ) END
                            FROM history_turns t WHERE t.session_key=s.key
                            ORDER BY t.ordinal DESC LIMIT 1) AS unfinished
                    FROM sessions s WHERE s.key GLOB ?
                )
                SELECT key, unfinished FROM scan WHERE journaled OR unfinished ORDER BY updated_at DESC, tie
            """, (f"{key_prefix}*",))
            return [(key, bool(unfinished)) for key, unfinished in rows]

    def read_history_header(self, key: str) -> SessionHistoryPayload | None:
        """Read search identity and metadata without runtime checkpoints or inputs."""
        with self.transaction(write=False) as db:
            row = db.execute(
                "SELECT created_at, updated_at, metadata, generation FROM sessions WHERE key=?", (key,),
            ).fetchone()
            if row is None:
                return None
            return {"key": key, "created_at": datetime.fromisoformat(row[0]).isoformat(),
                    "updated_at": datetime.fromisoformat(row[1]).isoformat(),
                    "metadata": _object(row[2]), "generation": row[3]}

    def project_session_messages(
        self,
        key: str,
        project: Callable[[SessionHistoryPayload, Iterator[tuple[int, dict[str, Any]]]], _T],
    ) -> _T | None:
        """Project the header and canonical messages without materializing history."""
        with self.transaction(write=False) as db:
            header = self.read_history_header(key)
            if header is None:
                return None
            # Indices refer to the ordered message list, not SQLite positions.
            # Count first so sparse positions retain the same observable indices.
            count = db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_key=?", (key,),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT record FROM messages WHERE session_key=? ORDER BY position DESC", (key,),
            )
            messages = ((count - 1 - index, _object(row[0])) for index, row in enumerate(rows))
            try:
                return project(header, messages)
            finally:
                rows.close()

    def list_handle_metadata(self) -> list[dict[str, Any]]:
        """Read just the allocation headers, irrespective of archive membership."""
        with self.transaction(write=False) as db:
            rows = db.execute(f"""
                SELECT key, created_at, json_extract(metadata, '$.session_handle'),
                    CASE WHEN json_type(metadata, '$.{SESSION_TYPE_KEY}') IS NULL THEN ?
                         ELSE json_extract(metadata, '$.{SESSION_TYPE_KEY}') END
                FROM sessions
            """, (CONVERSATION.name,))
            return [{"key": key, "created_at": created,
                     "metadata": {"session_handle": name, SESSION_TYPE_KEY: kind}}
                    for key, created, name, kind in rows]

    def project_session_handle_names(
        self, project: Callable[[Iterator[tuple[str, object]]], _T],
    ) -> _T:
        """Stream stored names for handle ambiguity checks in the caller's snapshot."""
        with self.transaction(write=False) as db:
            rows = db.execute("SELECT key, json_extract(metadata, '$.session_handle') FROM sessions")
            try:
                return project((str(row[0]), cast(object, row[1])) for row in rows)
            finally:
                rows.close()

    def read(self, key: str) -> SessionPayload | None:
        session = self.load(key)
        if session is None:
            return None
        return {"key": key, "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata, "messages": session.messages}

    def migrate_history(
        self, name: str, collect: Callable[[list[SessionInfo]], list[HistoryImport]],
    ) -> None:
        """Commit a channel-owned legacy import and its once-only marker together."""
        with self.transaction() as db:
            marker = db.execute("SELECT value FROM storage_meta WHERE key=?", (name,)).fetchone()
            if marker is not None:
                if marker[0] != "complete":
                    raise RuntimeError(f"invalid history import marker: {name}")
                return
            for item in collect(self.list_sessions()):
                session = self.load(item.key, history=False)
                if session is None:
                    session = Session(key=item.key)
                    if item.created_at_ms:
                        session.created_at = datetime.fromtimestamp(item.created_at_ms / 1000)
                    if item.updated_at_ms:
                        session.updated_at = datetime.fromtimestamp(item.updated_at_ms / 1000)
                    self.save(session)
                revision = self.project_history(item.key, lambda reader: reader.revision)
                if revision is not None and revision[1] >= 0:
                    raise SessionConflictError(f"history already exists before import: {item.key}")
                self.append_history(item.key, item.facts, expected_generation=session.generation)
                db.execute("UPDATE history_heads SET updated_at_ms=max(updated_at_ms, ?) WHERE session_key=?",
                           (item.updated_at_ms, item.key))
                # Import ownership survives deletion: another namespace must not
                # mistake this instance-wide backup for a new orphan later.
                db.execute("INSERT INTO storage_meta (key, value) VALUES (?, 'complete')", (f"{name}:{item.key}",))
            db.execute("INSERT INTO storage_meta (key, value) VALUES (?, 'complete')", (name,))

    def project_history(self, key: str, project: Callable[[HistoryReader], _T]) -> _T:
        """Project durable display facts and canonical messages from one snapshot."""
        with self.transaction(write=False) as db:
            return project(HistoryReader(db, key, self.path))

    def append_history(
        self, key: str, facts: list[HistoryFact], *, expected_generation: str | None,
        skip_invalid: bool = False,
    ) -> list[str]:
        encoded: list[tuple[HistoryKind, int, str, str]] = []
        errors: list[str] = []
        for fact in facts:
            try:
                record = fact.encode()
                # Freeze all transaction inputs from the encoded snapshot; never
                # revisit mutable content after serialization has completed.
                preview = ""
                if fact.kind in {HistoryKind.INPUT, HistoryKind.ANSWER, HistoryKind.ANSWER_SEGMENT}:
                    preview = message_preview_text({"content": json.loads(record)["content"].get("text", "")})
                encoded.append((fact.kind, fact.created_at_ms, record, preview))
            except (ValueError, TypeError) as exc:
                if not skip_invalid:
                    raise
                errors.append(str(exc))
        if not encoded and errors:
            return errors
        with self.transaction() as db:
            row = db.execute("SELECT generation FROM sessions WHERE key=?", (key,)).fetchone()
            if row is None or (expected_generation is not None and row[0] != expected_generation):
                raise SessionConflictError("history belongs to a deleted or replaced session")
            db.execute("INSERT OR IGNORE INTO history_heads (session_key) VALUES (?)", (key,))
            tail = db.execute(
                "SELECT ordinal, record_count, completed FROM history_turns WHERE session_key=? ORDER BY ordinal DESC LIMIT 1",
                (key,),
            ).fetchone()
            ordinal, position = (int(tail[0]), int(tail[1])) if tail is not None else (0, 0)
            completed = tail is not None and bool(tail[2])
            appended = False
            for kind, created_at_ms, record, preview in encoded:
                if kind is HistoryKind.INPUT and db.execute(
                    """SELECT 1 FROM history_entries WHERE session_key=? AND kind='input'
                       AND json_extract(record, '$.content.input_id')=json_extract(?, '$.content.input_id')""",
                    (key, record),
                ).fetchone() is not None:
                    continue
                appended = True
                if completed:
                    ordinal, position = ordinal + 1, 0
                if position == 0:
                    db.execute(
                        "INSERT INTO history_turns VALUES (?, ?, 0, 0, 0, 0)", (key, ordinal),
                    )
                db.execute("INSERT INTO history_entries VALUES (?, ?, ?, ?, ?)", (
                    key, ordinal, position, kind.value, record,
                ))
                completed = kind is HistoryKind.COMPLETION
                db.execute(
                    """UPDATE history_turns SET record_count=record_count+1, byte_count=byte_count+?,
                       user_count=user_count+?, completed=? WHERE session_key=? AND ordinal=?""",
                    (history_record_size(record), int(kind is HistoryKind.INPUT),
                     int(completed), key, ordinal),
                )
                position += 1
                if preview:
                    field = "user_preview" if kind is HistoryKind.INPUT else "preview"
                    db.execute(f"UPDATE history_heads SET {field}=? WHERE session_key=? AND {field}=''", (preview, key))
                db.execute("UPDATE history_heads SET updated_at_ms=max(updated_at_ms, ?) WHERE session_key=?",
                           (created_at_ms, key))
            if appended:
                db.execute("UPDATE history_heads SET revision=revision+1 WHERE session_key=?", (key,))
        return errors

    def _truncate_display_history(self, key: str, ordinal: int, position: int) -> None:
        """Drop a display suffix and rebuild its paging/sidebar summaries before appending."""
        with self.transaction() as db:
            db.execute(
                """DELETE FROM history_entries WHERE session_key=?
                   AND (turn_ordinal>? OR (turn_ordinal=? AND position>=?))""",
                (key, ordinal, ordinal, position),
            )
            db.execute("DELETE FROM history_turns WHERE session_key=? AND ordinal>?", (key, ordinal))
            counts = db.execute(
                """SELECT count(*), coalesce(sum(coalesce(json_extract(record, '$.uncompressed_bytes'),
                                                        length(CAST(record AS BLOB)))), 0),
                          coalesce(sum(kind=?), 0)
                   FROM history_entries WHERE session_key=? AND turn_ordinal=?""",
                (HistoryKind.INPUT, key, ordinal),
            ).fetchone()
            if counts[0]:
                db.execute(
                    """UPDATE history_turns SET record_count=?, byte_count=?, user_count=?, completed=0
                       WHERE session_key=? AND ordinal=?""", (*counts, key, ordinal),
                )
            else:
                db.execute("DELETE FROM history_turns WHERE session_key=? AND ordinal=?", (key, ordinal))
            preview = user_preview = ""
            for row in db.execute(
                """SELECT kind, json_extract(record, '$.content.text') FROM history_entries
                   WHERE session_key=? AND kind IN (?, ?, ?) ORDER BY turn_ordinal, position""",
                (key, HistoryKind.INPUT, HistoryKind.ANSWER, HistoryKind.ANSWER_SEGMENT),
            ):
                text = message_preview_text({"content": row[1] or ""})
                if row[0] == HistoryKind.INPUT:
                    user_preview = user_preview or text
                else:
                    preview = preview or text
                if preview and user_preview:
                    break
            updated_at_ms = db.execute(
                "SELECT coalesce(max(json_extract(record, '$.created_at_ms')), 0) FROM history_entries WHERE session_key=?",
                (key,),
            ).fetchone()[0]
            db.execute(
                "UPDATE history_heads SET preview=?, user_preview=?, updated_at_ms=? WHERE session_key=?",
                (preview, user_preview, updated_at_ms, key),
            )

    def save_fork(
        self, source: Session, target: Session, display_suffix: Callable[[], list[HistoryFact]], *,
        replace_at: tuple[int, int, int] | None = None,
    ) -> None:
        """Commit the model and display branches together; keep retained rows for an in-place fork."""
        with self.transaction() as db:
            start = 0
            if replace_at is not None:
                start, ordinal, position = replace_at
                changed = db.execute(
                    "UPDATE sessions SET generation=? WHERE key=? AND generation=? AND revision=?",
                    (target.generation, target.key, source.generation, source.revision),
                ).rowcount
                if changed != 1:
                    raise SessionConflictError("session history changed")
                self._truncate_display_history(target.key, ordinal, position)
            self.save(target, message_start=start)
            if facts := display_suffix():
                self.append_history(target.key, facts, expected_generation=target.generation)

    def fork_before_user_index(
        self, source: Session, target_key: str, before_user_index: int, *, exclude_metadata: frozenset[str],
        title: str | None = None, history_projection: Callable[[Session], list[HistoryFact]] | None = None,
    ) -> Session | None:
        """Materialize a new fork within the transaction that loaded its source."""
        target = fork_session(source, target_key, before_user_index, exclude_metadata=exclude_metadata)
        if target is None:
            return None
        if title:
            target.metadata["title"] = title

        def display_suffix() -> list[HistoryFact]:
            facts = self.project_history(source.key, lambda reader: reader.fork_prefix(before_user_index))
            if facts is None:
                if history_projection is None:
                    return []
                facts = history_projection(target)
            facts.append(HistoryFact(HistoryKind.FORK_BOUNDARY, created_at_ms=int(target.created_at.timestamp() * 1000)))
            return facts

        self.save_fork(source, target, display_suffix)
        return target


    def archives_imported(self) -> bool:
        with self.transaction(write=False) as db:
            return db.execute("SELECT 1 FROM storage_meta WHERE key='session_archives_imported'").fetchone() is not None

    def archived_keys(self) -> list[str]:
        with self.transaction(write=False) as db:
            encoded = db.execute("SELECT json_group_array(key) FROM (SELECT key FROM session_archives ORDER BY key)").fetchone()[0]
            return cast(list[str], json.loads(encoded))

    def import_archives(self, keys: list[str]) -> list[str]:
        with self.transaction() as db:
            if db.execute("INSERT OR IGNORE INTO storage_meta (key, value) VALUES ('session_archives_imported', '1')").rowcount:
                self.set_archived(keys, True)
            return self.archived_keys()

    def set_archived(self, keys: list[str], archived: bool) -> None:
        with self.transaction() as db:
            if archived:
                db.execute("""
                    INSERT INTO session_archives (key, archived_at)
                    SELECT key, ? FROM sessions WHERE key IN (SELECT value FROM json_each(?))
                    ON CONFLICT(key) DO NOTHING
                """, (datetime.now().isoformat(), _encode(keys)))
            else:
                db.execute("DELETE FROM session_archives WHERE key IN (SELECT value FROM json_each(?))", (_encode(keys),))

    def delete(self, key: str, *, preserve_archive: bool = False) -> bool:
        with self.transaction() as db:
            archived = False
            if not preserve_archive:
                archived = db.execute("DELETE FROM session_archives WHERE key=?", (key,)).rowcount > 0
            deleted = db.execute("DELETE FROM sessions WHERE key=?", (key,)).rowcount > 0
            return archived or deleted

    def list_sessions(self) -> list[SessionInfo]:
        with self.transaction(write=False) as db:
            return [SessionInfo(key=row[0], created_at=row[1], updated_at=row[2],
                                title=row[3], preview=row[4], path=str(self.path))
                    for row in db.execute("SELECT key, created_at, updated_at, title, preview FROM sessions ORDER BY updated_at DESC")]

    def child_session_keys(self, parent_key: str) -> list[str]:
        """Find all persisted child kinds without decoding unrelated metadata."""
        with self.transaction(write=False) as db:
            return [row[0] for row in db.execute(
                f"""SELECT key FROM sessions
                    WHERE json_extract(metadata, '$.{PARENT_SESSION_KEY}')=?
                    AND json_type(metadata, '$.{PARENT_SESSION_KEY}')='text'
                    ORDER BY updated_at DESC""",
                (parent_key,),
            )]

    def typed_session_headers(self, session_type: str) -> list[tuple[str, dict[str, Any]]]:
        """Read just this owner's metadata, without rehydrating messages, checkpoints or inputs."""
        with self.transaction(write=False) as db:
            return [(key, _object(metadata)) for key, metadata in db.execute(
                f"""SELECT key, metadata FROM sessions WHERE json_extract(metadata, '$.{SESSION_TYPE_KEY}')=?
                    ORDER BY updated_at DESC, rowid""", (session_type,),
            )]

    def list_child_session_metadata(self, parent_key: str) -> list[SessionMetadataPayload]:
        """Read child headers from one snapshot, excluding checkpoints and pending inputs."""
        with self.transaction(write=False) as db:
            return [{"key": row[0], "created_at": row[1], "updated_at": row[2],
                     "metadata": _object(row[3])}
                    for row in db.execute(
                        f"""SELECT key, created_at, updated_at, metadata FROM sessions
                            WHERE json_extract(metadata, '$.{PARENT_SESSION_KEY}')=?
                            AND json_type(metadata, '$.{PARENT_SESSION_KEY}')='text'
                            ORDER BY updated_at DESC""",
                        (parent_key,),
                    )]

    def list_subagent_session_metadata(
        self, parent_key: str, *, turn_ids: Sequence[str],
    ) -> list[SessionMetadataPayload]:
        """Read only subagent headers attributed to the requested parent turns."""
        turns = [value for value in turn_ids if value]
        if not turns:
            return []
        with self.transaction(write=False) as db:
            return [{"key": row[0], "created_at": row[1], "updated_at": row[2],
                     "metadata": _object(row[3])}
                    for row in db.execute(_SUBAGENT_METADATA_QUERY, (parent_key, _encode(turns)))]

    def read_child_session_metadata(
        self, parent_key: str, child_keys: Sequence[str],
    ) -> list[SessionMetadataPayload]:
        """Read named child headers in one query, excluding checkpoints and pending inputs."""
        keys = [key for key in child_keys if key]
        if not keys:
            return []
        with self.transaction(write=False) as db:
            return [{"key": row[0], "created_at": row[1], "updated_at": row[2],
                     "metadata": _object(row[3])}
                    for row in db.execute(
                        f"""SELECT key, created_at, updated_at, metadata FROM sessions
                            WHERE key IN (SELECT value FROM json_each(?))
                            AND json_extract(metadata, '$.{PARENT_SESSION_KEY}')=?
                            AND json_type(metadata, '$.{PARENT_SESSION_KEY}')='text'""",
                        (_encode(keys), parent_key),
                    )]

    def list_metadata(self, *, archived: bool | None = None) -> list[dict[str, Any]]:
        archive_join = "JOIN" if archived is True else "LEFT JOIN"
        archive_filter = "WHERE session_archives.key IS NULL" if archived is False else ""
        with self.transaction(write=False) as db:
            # Fetch one value so a large list does not cross the Python/SQLite
            # iterator boundary for every session while other workers are busy.
            encoded = db.execute(f"""
                SELECT json_group_array(json_object(
                    'key', key, 'created_at', created_at, 'updated_at', updated_at,
                    'archived', archived, 'title', title, 'preview', preview, 'visible_updated_at', visible_updated_at,
                    'metadata', metadata, 'history_updated_at_ms', history_updated_at_ms,
                    'history_preview', history_preview
                )) FROM (
                    SELECT sessions.*, session_archives.key IS NOT NULL AS archived,
                           coalesce(history_heads.updated_at_ms, 0) AS history_updated_at_ms,
                           coalesce(nullif(history_heads.user_preview, ''), history_heads.preview, '') AS history_preview
                    FROM sessions {archive_join} session_archives ON session_archives.key=sessions.key
                    LEFT JOIN history_heads ON history_heads.session_key=sessions.key
                    {archive_filter}
                    ORDER BY sessions.updated_at DESC
                )
            """).fetchone()[0]
            rows = cast(list[dict[str, Any]], json.loads(encoded))
            for row in rows:
                row["path"] = str(self.path)
                row["metadata"] = _object(row["metadata"])
            return rows
