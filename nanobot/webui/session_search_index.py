"""FTS5 search mirror for persisted session content.

Session search used to scan every candidate JSONL transcript on each query.
This module maintains a per-workspace SQLite FTS5 index beside the JSONL
store: it is reconciled incrementally on every search, and any index failure
falls back to the original JSONL scan so the JSONL files stay the single
source of truth.

Index row granularity follows the WebUI session list index: one row per
session whose ``content`` is title plus the bounded preview text (the same
records the WebUI sidebar surfaces). Message-level keyword search inside a
matched session is handled elsewhere (``WebuiSessionAccess._messages``); this
index exists to make finding candidate sessions fast.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager

_INDEX_VERSION = 1
_INDEX_FILENAME = ".webui_session_search.db"
_SCHEMA = (
    "CREATE VIRTUAL TABLE session_search USING fts5("
    "content, session_key UNINDEXED, signature UNINDEXED, "
    "tokenize = 'trigram')"
)
_MIN_QUERY_LEN = 3

# Field names mirrored from nanobot.webui.session_list_index (kept private
# there; duplicated to avoid expanding that module's public surface).
_ROW_SOURCE = "_source"
_ACTIVITY_MTIME_FIELD = "webui_activity_mtime_ns"
_ACTIVITY_SIZE_FIELD = "webui_activity_size"
_ACTIVITY_FILES_FIELD = "webui_activity_files"


def _row_identity(row: dict[str, Any]) -> str:
    key = row.get("key")
    if isinstance(key, str) and key:
        return str(key)
    return f"file:{row.get(_ROW_SOURCE)}:{row.get('file')}"


def _row_content(row: dict[str, Any]) -> str:
    title = row.get("title")
    preview = row.get("preview")
    return "\n".join(
        text.strip()
        for text in (title, preview)
        if isinstance(text, str) and text.strip()
    )


def _row_signature(row: dict[str, Any]) -> str:
    signature = {
        "mtime_ns": row.get("mtime_ns"),
        "size": row.get("size"),
        "activity_mtime_ns": row.get(_ACTIVITY_MTIME_FIELD),
        "activity_size": row.get(_ACTIVITY_SIZE_FIELD),
        "activity_files": row.get(_ACTIVITY_FILES_FIELD),
        "updated_at": row.get("updated_at"),
        "content_preview": _row_content(row),
    }
    return json.dumps(signature, ensure_ascii=False, sort_keys=True)


def _message_text(message: dict[str, Any]) -> str:
    """Same extraction rule as WebuiSessionAccess._message_text: plain string or
    the joined ``text`` blocks of a structured content list."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for raw_block in cast(list[object], content):
        if not isinstance(raw_block, dict):
            continue
        block = cast(dict[object, object], raw_block)
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def _escape_fts5_phrase(text: str) -> str:
    """Quote *text* as one FTS5 phrase; trigram phrases act as substring match."""
    return '"' + text.replace('"', '""') + '"'


class SessionSearchIndex:
    """Reconciled-on-use FTS5 mirror over WebUI session list rows.

    All methods are safe to call from multiple threads and never raise:
    index failures disable or rebuild the mirror while callers fall back to
    the legacy JSONL scan.
    """

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions
        self._db_path = sessions.sessions_dir / _INDEX_FILENAME
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._disabled = False

    # -- connection lifecycle ----------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS search_meta"
                " (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
            )
            row = conn.execute(
                "SELECT v FROM search_meta WHERE k = 'version'"
            ).fetchone()
            if row is None or row[0] != str(_INDEX_VERSION):
                # Unknown or outdated schema: rebuild from scratch.
                conn.execute("DROP TABLE IF EXISTS session_search")
                conn.execute(_SCHEMA)
                conn.execute(
                    "INSERT OR REPLACE INTO search_meta (k, v) VALUES ('version', ?)",
                    (str(_INDEX_VERSION),),
                )
                conn.commit()
        except Exception:
            conn.close()
            raise
        self._conn = conn
        return conn

    def _teardown(self) -> None:
        """Close and delete the index so the next use rebuilds it fresh."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(f"{self._db_path}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass

    def _disable(self, reason: str, exc: BaseException) -> None:
        logger.debug("Session search index disabled ({}): {}", reason, exc)
        self._disabled = True
        self._teardown()

    def _usable(self) -> bool:
        if self._disabled:
            return False
        try:
            self._connect()
            return True
        except (sqlite3.Error, OSError) as e:
            self._disable("open failed", e)
            return False

    # -- reconciliation ------------------------------------------------------

    def _transcript_texts(self, session_key: str) -> list[str]:
        """Extract text from WebUI transcript events (active + segments).

        WebUI transcripts are a separate store from the JSONL session file;
        legacy search reads both, so the index must cover both. Any string
        ``text`` field from any event is included (over-indexing is harmless:
        the legacy excerpt generator still filters exactly).
        """
        from nanobot.webui.transcript import (
            webui_transcript_path,
            webui_transcript_segments_dir,
        )

        paths = [webui_transcript_path(session_key)]
        segments_dir = webui_transcript_segments_dir(session_key)
        if segments_dir.is_dir():
            paths.extend(sorted(segments_dir.glob("*.jsonl")))
        texts: list[str] = []
        for path in paths:
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        text = record.get("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
            except OSError:
                continue
        return texts

    def _session_content(self, row: dict[str, Any]) -> str:
        """Full searchable text for a session: title, visible messages, and
        WebUI transcript texts."""
        parts: list[str] = []
        title = row.get("title")
        if isinstance(title, str) and title.strip():
            parts.append(title.strip())
        key = row.get("key")
        if isinstance(key, str) and key:
            payload = self._sessions.read_session_file(key)
            if payload is not None:
                raw_messages = payload.get("messages")
                if isinstance(raw_messages, list):
                    for message in cast(list[object], raw_messages):
                        if not isinstance(message, dict):
                            continue
                        text = _message_text(cast(dict[str, Any], message))
                        if text:
                            parts.append(text)
            parts.extend(self._transcript_texts(key))
        return "\n".join(parts)

    def _reconcile(self, conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        current = {_row_identity(row): row for row in rows}
        stored = dict(
            (cast(str, identity), cast(str, signature))
            for identity, signature in conn.execute(
                "SELECT session_key, signature FROM session_search"
            )
        )
        stale: list[str] = []
        missing: list[str] = []
        for identity, row in current.items():
            existing = stored.pop(identity, None)
            if existing is None:
                missing.append(identity)
            elif existing != _row_signature(row):
                stale.append(identity)
        # Anything left in *stored* no longer exists on disk.
        stale.extend(stored)
        if not stale and not missing:
            return
        with conn:
            for identity in stale:
                conn.execute(
                    "DELETE FROM session_search WHERE session_key = ?", (identity,)
                )
            for identity in missing + stale:
                row = current.get(identity)
                if row is not None:
                    conn.execute(
                        "INSERT INTO session_search (content, session_key, signature)"
                        " VALUES (?, ?, ?)",
                        (self._session_content(row), identity, _row_signature(row)),
                    )

    def _load_rows(self) -> list[dict[str, Any]]:
        from nanobot.webui.session_list_index import list_webui_sessions

        return list_webui_sessions(self._sessions)

    # -- public API ------------------------------------------------------------

    def matching_session_keys(self, query: str) -> list[str] | None:
        """Return session keys whose indexed content contains *query*.

        Returns ``None`` when the index is unavailable or the query is below
        the trigram minimum length, so callers fall back to the legacy JSONL
        scan. An empty list means the index is healthy and nothing matched.
        """
        needle = query.strip().casefold()
        if len(needle) < _MIN_QUERY_LEN or not self._usable():
            return None
        with self._lock:
            try:
                conn = self._connect()
                self._reconcile(conn, self._load_rows())
                hits = conn.execute(
                    "SELECT session_key FROM session_search"
                    " WHERE session_search MATCH ?",
                    (_escape_fts5_phrase(needle),),
                ).fetchall()
            except sqlite3.Error as e:
                logger.warning(
                    "Session search index query failed; falling back to JSONL scan: {}",
                    e,
                )
                self._teardown()
                return None
            except Exception as e:  # never let index errors break search
                self._disable("unexpected failure", e)
                return None
        return [
            identity
            for (identity,) in hits
            if isinstance(identity, str) and not identity.startswith("file:")
        ]
