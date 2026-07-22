"""Indexed persistence for WebUI display transcripts.

The WebSocket runtime emits many small display events while a turn is running.  This
module keeps those writes off the gateway event loop and stores them in an indexed
SQLite read model.  Reads page by turn ordinal, so opening a conversation never scans
the full transcript.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_SCHEMA_VERSION = 2
_MAX_EVENT_BYTES = 8 * 1024 * 1024
_DEFAULT_BUSY_TIMEOUT_MS = 30_000
_DEFAULT_WRITE_BATCH_WINDOW_S = 0.05
_DEFAULT_WRITE_BATCH_SIZE = 256

LegacyLoader = Callable[[str], list[dict[str, Any]]]


@dataclass(frozen=True)
class StoredTurn:
    """One persisted turn and its ordered display events."""

    ordinal: int
    records: list[dict[str, Any]]


class SQLiteTranscriptStore:
    """Synchronous indexed transcript repository.

    Callers choose the execution context.  The gateway uses :class:`TranscriptWriteQueue`
    for writes and ``asyncio.to_thread`` for reads; focused tests and migration helpers can
    call the repository directly.
    """

    def __init__(self, path: Path, *, legacy_loader: LegacyLoader | None = None) -> None:
        self.path = path
        self._legacy_loader = legacy_loader
        self._initialized = False
        self._initialize_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self._initialize()
        connection = sqlite3.connect(self.path, timeout=_DEFAULT_BUSY_TIMEOUT_MS / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_DEFAULT_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=_DEFAULT_BUSY_TIMEOUT_MS / 1000)
            try:
                connection.execute(f"PRAGMA busy_timeout = {_DEFAULT_BUSY_TIMEOUT_MS}")
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version not in {0, 1, _SCHEMA_VERSION}:
                    raise RuntimeError(
                        f"unsupported WebUI transcript schema {version}; "
                        f"expected {_SCHEMA_VERSION}"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transcript_sessions (
                        session_key TEXT PRIMARY KEY,
                        legacy_imported INTEGER NOT NULL DEFAULT 0,
                        next_sequence INTEGER NOT NULL DEFAULT 0,
                        active_turn INTEGER NOT NULL DEFAULT 0,
                        next_user_index INTEGER NOT NULL DEFAULT 0,
                        activity_revision INTEGER NOT NULL DEFAULT 0,
                        activity_updated_at_ns INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transcript_turns (
                        session_key TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        finalized INTEGER NOT NULL DEFAULT 0,
                        user_offset INTEGER NOT NULL DEFAULT 0,
                        user_count INTEGER NOT NULL DEFAULT 0,
                        event_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (session_key, ordinal),
                        FOREIGN KEY (session_key)
                            REFERENCES transcript_sessions(session_key)
                            ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transcript_events (
                        session_key TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        turn_ordinal INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (session_key, sequence),
                        FOREIGN KEY (session_key, turn_ordinal)
                            REFERENCES transcript_turns(session_key, ordinal)
                            ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS transcript_events_by_turn
                        ON transcript_events(session_key, turn_ordinal, sequence)
                    """
                )
                session_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(transcript_sessions)")
                }
                if "activity_revision" not in session_columns:
                    connection.execute(
                        """
                        ALTER TABLE transcript_sessions
                        ADD COLUMN activity_revision INTEGER NOT NULL DEFAULT 0
                        """
                    )
                if "activity_updated_at_ns" not in session_columns:
                    connection.execute(
                        """
                        ALTER TABLE transcript_sessions
                        ADD COLUMN activity_updated_at_ns INTEGER NOT NULL DEFAULT 0
                        """
                    )
                if version < _SCHEMA_VERSION:
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
            self._initialized = True

    @staticmethod
    def _serialize_record(record: dict[str, Any]) -> str:
        raw = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError("webui transcript event too large")
        return raw

    def _is_imported(self, session_key: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT legacy_imported FROM transcript_sessions WHERE session_key = ?",
                (session_key,),
            ).fetchone()
        return row is not None and bool(row["legacy_imported"])

    def ensure_imported(self, session_key: str) -> None:
        """Import a legacy JSONL transcript once, preserving the source files."""
        if self._is_imported(session_key):
            return
        records = self._legacy_loader(session_key) if self._legacy_loader is not None else []
        serialized = [(record, self._serialize_record(record)) for record in records]

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT legacy_imported FROM transcript_sessions WHERE session_key = ?",
                (session_key,),
            ).fetchone()
            if row is not None and bool(row["legacy_imported"]):
                connection.rollback()
                return
            connection.execute(
                """
                INSERT INTO transcript_sessions (
                    session_key, legacy_imported, next_sequence, active_turn
                ) VALUES (?, 0, 0, 0)
                ON CONFLICT(session_key) DO NOTHING
                """,
                (session_key,),
            )
            if serialized:
                self._append_serialized(connection, session_key, serialized)
            connection.execute(
                "UPDATE transcript_sessions SET legacy_imported = 1 WHERE session_key = ?",
                (session_key,),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _append_serialized(
        self,
        connection: sqlite3.Connection,
        session_key: str,
        records: list[tuple[dict[str, Any], str]],
    ) -> None:
        row = connection.execute(
            """
            SELECT next_sequence, active_turn, next_user_index
            FROM transcript_sessions
            WHERE session_key = ?
            """,
            (session_key,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"transcript session was not initialized: {session_key}")
        sequence = int(row["next_sequence"])
        turn_ordinal = int(row["active_turn"])
        next_user_index = int(row["next_user_index"])

        for record, payload in records:
            is_user = int(record.get("event") == "user" or record.get("role") == "user")
            connection.execute(
                """
                INSERT INTO transcript_turns (
                    session_key, ordinal, finalized, user_offset, user_count, event_count
                ) VALUES (?, ?, 0, ?, ?, 1)
                ON CONFLICT(session_key, ordinal) DO UPDATE SET
                    user_count = user_count + excluded.user_count,
                    event_count = event_count + 1
                """,
                (session_key, turn_ordinal, next_user_index, is_user),
            )
            connection.execute(
                """
                INSERT INTO transcript_events (
                    session_key, sequence, turn_ordinal, payload
                ) VALUES (?, ?, ?, ?)
                """,
                (session_key, sequence, turn_ordinal, payload),
            )
            sequence += 1
            next_user_index += is_user
            if record.get("event") == "turn_end":
                connection.execute(
                    """
                    UPDATE transcript_turns
                    SET finalized = 1
                    WHERE session_key = ? AND ordinal = ?
                    """,
                    (session_key, turn_ordinal),
                )
                turn_ordinal += 1

        connection.execute(
            """
            UPDATE transcript_sessions
            SET next_sequence = ?, active_turn = ?, next_user_index = ?
            WHERE session_key = ?
            """,
            (sequence, turn_ordinal, next_user_index, session_key),
        )

    def append_batch(self, entries: list[tuple[str, dict[str, Any]]]) -> None:
        if not entries:
            return
        grouped: dict[str, list[tuple[dict[str, Any], str]]] = {}
        for session_key, record in entries:
            grouped.setdefault(session_key, []).append((record, self._serialize_record(record)))
        for session_key in grouped:
            self.ensure_imported(session_key)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            activity_ns = time.time_ns()
            for session_key, records in grouped.items():
                self._append_serialized(connection, session_key, records)
                self._touch_activity(connection, session_key, activity_ns)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replace(self, session_key: str, records: list[dict[str, Any]]) -> None:
        serialized = [(record, self._serialize_record(record)) for record in records]
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM transcript_sessions WHERE session_key = ?",
                (session_key,),
            )
            connection.execute(
                """
                INSERT INTO transcript_sessions (
                    session_key, legacy_imported, next_sequence, active_turn
                ) VALUES (?, 1, 0, 0)
                """,
                (session_key,),
            )
            if serialized:
                self._append_serialized(connection, session_key, serialized)
            self._touch_activity(connection, session_key, time.time_ns())
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _touch_activity(
        connection: sqlite3.Connection,
        session_key: str,
        activity_ns: int,
    ) -> None:
        connection.execute(
            """
            UPDATE transcript_sessions
            SET activity_revision = activity_revision + 1,
                activity_updated_at_ns = MAX(activity_updated_at_ns, ?)
            WHERE session_key = ?
            """,
            (activity_ns, session_key),
        )

    def delete(self, session_key: str) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM transcript_sessions WHERE session_key = ?",
                (session_key,),
            )
            connection.commit()
            return cursor.rowcount > 0
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def read_turn_batch(
        self,
        session_key: str,
        *,
        before_ordinal: int | None = None,
        limit: int = 64,
    ) -> list[StoredTurn]:
        self.ensure_imported(session_key)
        upper = before_ordinal if before_ordinal is not None else 2**63 - 1
        with closing(self._connect()) as connection:
            turn_rows = connection.execute(
                """
                SELECT ordinal
                FROM transcript_turns
                WHERE session_key = ? AND ordinal < ?
                ORDER BY ordinal DESC
                LIMIT ?
                """,
                (session_key, upper, max(1, limit)),
            ).fetchall()
            ordinals = [int(row["ordinal"]) for row in turn_rows]
            if not ordinals:
                return []
            placeholders = ",".join("?" for _ in ordinals)
            event_rows = connection.execute(
                f"""
                SELECT turn_ordinal, payload
                FROM transcript_events
                WHERE session_key = ? AND turn_ordinal IN ({placeholders})
                ORDER BY turn_ordinal DESC, sequence ASC
                """,
                (session_key, *ordinals),
            ).fetchall()

        records_by_turn: dict[int, list[dict[str, Any]]] = {ordinal: [] for ordinal in ordinals}
        for row in event_rows:
            payload = json.loads(str(row["payload"]))
            if isinstance(payload, dict):
                records_by_turn[int(row["turn_ordinal"])].append(payload)
        return [StoredTurn(ordinal, records_by_turn[ordinal]) for ordinal in ordinals]

    def activity_signatures(self) -> dict[str, dict[str, int]]:
        """Return per-session activity revisions without importing legacy files."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT session_key, activity_revision, activity_updated_at_ns
                FROM transcript_sessions
                WHERE activity_revision > 0
                """
            ).fetchall()
        return {
            str(row["session_key"]): {
                "revision": int(row["activity_revision"]),
                "updated_at_ns": int(row["activity_updated_at_ns"]),
            }
            for row in rows
        }

    def read_all(self, session_key: str) -> list[dict[str, Any]]:
        self.ensure_imported(session_key)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM transcript_events
                WHERE session_key = ?
                ORDER BY sequence ASC
                """,
                (session_key,),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def user_count_before(self, session_key: str, ordinal: int) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_offset
                FROM transcript_turns
                WHERE session_key = ? AND ordinal = ?
                """,
                (session_key, ordinal),
            ).fetchone()
        return int(row["user_offset"]) if row is not None else 0

    def has_turn_before(self, session_key: str, ordinal: int) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM transcript_turns
                WHERE session_key = ? AND ordinal < ?
                LIMIT 1
                """,
                (session_key, ordinal),
            ).fetchone()
        return row is not None

    def fork_before_user_index(
        self,
        source_key: str,
        target_key: str,
        before_user_index: int,
    ) -> bool:
        if before_user_index < 0:
            return False
        lines = self.read_all(source_key)
        if not lines:
            return False
        target_chat_id = target_key.split(":", 1)[1] if target_key.startswith("websocket:") else None
        copied: list[dict[str, Any]] = []
        user_index = 0
        found_target = False
        for row in lines:
            if row.get("event") == "fork_marker":
                continue
            if row.get("event") == "user" or row.get("role") == "user":
                if user_index == before_user_index:
                    found_target = True
                    break
                user_index += 1
            duplicate = json.loads(json.dumps(row, ensure_ascii=False))
            if target_chat_id is not None:
                duplicate["chat_id"] = target_chat_id
            copied.append(duplicate)
        if user_index == before_user_index:
            found_target = True
        if not found_target:
            return False
        self.replace(target_key, copied)
        return True


@dataclass
class _WriteCommand:
    kind: str
    entry: tuple[str, dict[str, Any]] | None = None
    action: Callable[[SQLiteTranscriptStore], Any] | None = None
    done: threading.Event | None = None
    result: Any = None
    error: BaseException | None = None


class TranscriptWriteQueue:
    """Single-writer queue that batches transcript persistence off the event loop."""

    def __init__(
        self,
        store: SQLiteTranscriptStore,
        *,
        log: Any,
        batch_window_s: float = _DEFAULT_WRITE_BATCH_WINDOW_S,
        batch_size: int = _DEFAULT_WRITE_BATCH_SIZE,
    ) -> None:
        self.store = store
        self._log = log
        self._batch_window_s = max(0.0, batch_window_s)
        self._batch_size = max(1, batch_size)
        self._queue: queue.Queue[_WriteCommand] = queue.Queue()
        self._state_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="nanobot-webui-transcript-writer",
            daemon=True,
        )
        self._closed = False
        self._failure: BaseException | None = None
        self._thread.start()

    def append(self, session_key: str, record: dict[str, Any]) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("webui transcript writer is closed")
            if self._failure is not None:
                raise RuntimeError("webui transcript writer has failed") from self._failure
            self._queue.put(_WriteCommand("append", entry=(session_key, record)))

    def call(self, action: Callable[[SQLiteTranscriptStore], Any]) -> Any:
        done = threading.Event()
        command = _WriteCommand("call", action=action, done=done)
        with self._state_lock:
            if self._closed:
                raise RuntimeError("webui transcript writer is closed")
            self._queue.put(command)
        done.wait()
        if command.error is not None:
            raise command.error
        return command.result

    def flush(self) -> None:
        self.call(lambda _store: None)

    def close(self) -> None:
        done = threading.Event()
        command = _WriteCommand("stop", done=done)
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(command)
        done.wait()
        self._thread.join()
        if command.error is not None:
            raise command.error

    def _record_failure(self, exc: BaseException) -> None:
        with self._state_lock:
            if self._failure is None:
                self._failure = exc

    def _write_batch(self, commands: list[_WriteCommand]) -> None:
        entries = [command.entry for command in commands if command.entry is not None]
        if not entries:
            return
        try:
            self.store.append_batch(entries)
        except Exception as exc:
            self._record_failure(exc)
            self._log.warning("webui transcript batch write failed: {}", exc)

    def _finish_control(self, command: _WriteCommand) -> bool:
        try:
            if self._failure is not None:
                raise RuntimeError("webui transcript writer has failed") from self._failure
            if command.kind == "call" and command.action is not None:
                command.result = command.action(self.store)
        except BaseException as exc:
            command.error = exc
        finally:
            if command.done is not None:
                command.done.set()
        return command.kind == "stop"

    def _run(self) -> None:
        deferred: _WriteCommand | None = None
        while True:
            command = deferred or self._queue.get()
            deferred = None
            if command.kind != "append":
                if self._finish_control(command):
                    return
                continue

            batch = [command]
            deadline = time.monotonic() + self._batch_window_s
            while len(batch) < self._batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    candidate = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if candidate.kind == "append":
                    batch.append(candidate)
                else:
                    deferred = candidate
                    break
            self._write_batch(batch)
