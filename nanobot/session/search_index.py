"""Rebuildable FTS5 candidates over canonical, public session history."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError
from contextlib import closing, suppress
from pathlib import Path
from typing import cast

from filelock import FileLock
from loguru import logger

from nanobot.session.manager import SessionManager

_INDEX_FILENAME = ".session_search.sqlite3"
_INDEX_VERSION = 2

_LoadContent = Callable[[str, Callable[[str], None]], None]


def _check_cancelled(cancelled: threading.Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()


class SessionSearchIndex:
    """Select candidates; the reader owns visibility, ordering and excerpts.

    The cache uses committed session identities for invalidation, so indexing
    never blocks session writes. Sessions changed during indexing are returned
    as candidates for the reader to check directly.
    """

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions
        self._path = sessions.sessions_dir / _INDEX_FILENAME
        self._lock = FileLock(str(self._path) + ".lock", timeout=1)

    def matching_session_keys(
        self,
        query: str,
        session_keys: list[str],
        load_content: _LoadContent,
        *, cancelled: threading.Event | None = None,
    ) -> set[str] | None:
        needle = query.casefold()
        if len(needle) < 3 or "\x00" in needle:
            return None
        try:
            with self._lock:
                _check_cancelled(cancelled)
                if self._path.is_symlink():
                    return None
                for attempt in range(2):
                    try:
                        return self._query(needle, session_keys, load_content, cancelled)
                    except sqlite3.DatabaseError as exc:
                        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                        if attempt or code not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                            raise
                        # All connections are closed before removing only our cache.
                        for suffix in ("", "-wal", "-shm"):
                            Path(str(self._path) + suffix).unlink(missing_ok=True)
        except (sqlite3.Error, OSError) as exc:
            _check_cancelled(cancelled)
            logger.debug("Session search cache unavailable; using canonical scan: {}", exc)
        return None

    def _signatures(
        self, session_keys: list[str], cancelled: threading.Event | None,
    ) -> dict[str, str]:
        versions = self._sessions.read_consistently(
            self._sessions.list_session_versions, cancelled=cancelled,
        )
        signatures: dict[str, str] = {}
        for key in session_keys:
            _check_cancelled(cancelled)
            version = versions.get(key)
            if version is None:
                continue
            signatures[key] = f"{version[0]}:{version[1]}"
        return signatures

    def _session_signature(self, key: str) -> str | None:
        version = self._sessions.read_session_version(key)
        return None if version is None else f"{version[0]}:{version[1]}"

    def _query(
        self,
        needle: str,
        session_keys: list[str],
        load_content: _LoadContent,
        cancelled: threading.Event | None,
    ) -> set[str]:
        signatures = self._signatures(session_keys, cancelled)
        with closing(sqlite3.connect(self._path, timeout=1)) as connection:
            if cancelled is not None:
                connection.set_progress_handler(cancelled.is_set, 1000)
            connection.execute("PRAGMA journal_mode = WAL")
            with connection:
                self._schema(connection)
                with suppress(OSError):
                    os.chmod(self._path, 0o600)
                indexed = self._reconcile(connection, signatures, load_content, cancelled)
                hits = self._matches(connection, needle)
        current = self._signatures(session_keys, cancelled)
        hits.update(key for key in current if current[key] != indexed.get(key))
        return hits

    @staticmethod
    def _matches(connection: sqlite3.Connection, needle: str) -> set[str]:
        phrase = '"' + needle.replace('"', '""') + '"'
        return {
            cast(str, key)
            for (key,) in connection.execute(
                "SELECT DISTINCT session_key FROM session_search "
                "WHERE session_search MATCH ?",
                (phrase,),
            )
        }

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA user_version").fetchone()[0] == _INDEX_VERSION:
            return
        connection.execute("DROP TABLE IF EXISTS session_search")
        connection.execute("DROP TABLE IF EXISTS search_manifest")
        connection.execute(
            "CREATE TABLE search_manifest "
            "(session_key TEXT PRIMARY KEY, signature TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE session_search USING fts5(session_key UNINDEXED, content, tokenize = 'trigram')"
        )
        connection.execute(f"PRAGMA user_version = {_INDEX_VERSION}")

    def _reconcile(
        self,
        connection: sqlite3.Connection,
        signatures: dict[str, str],
        load_content: _LoadContent,
        cancelled: threading.Event | None,
    ) -> dict[str, str]:
        stored = {
            key: signature
            for key, signature in cast(
                list[tuple[str, str]],
                connection.execute(
                    "SELECT session_key, signature FROM search_manifest"
                ).fetchall(),
            )
        }
        indexed = stored.copy()
        for key in stored.keys() - signatures.keys():
            _check_cancelled(cancelled)
            self._remove(connection, key)
            indexed.pop(key)
        for key, signature in signatures.items():
            _check_cancelled(cancelled)
            previous = stored.get(key)
            if previous == signature:
                continue
            if previous is not None:
                self._remove(connection, key)
                indexed.pop(key)

            def add_content(content: str) -> None:
                _check_cancelled(cancelled)
                connection.execute(
                    "INSERT INTO session_search (session_key, content) VALUES (?, ?)",
                    (key, content.replace("\x00", "").casefold()),
                )

            load_content(key, add_content)
            if self._session_signature(key) != signature:
                # A write raced this read; discard the partial entry so the
                # final signature check routes through direct verification.
                self._remove(connection, key)
                continue
            connection.execute(
                "INSERT INTO search_manifest (session_key, signature) VALUES (?, ?)",
                (key, signature),
            )
            indexed[key] = signature
        return indexed

    @staticmethod
    def _remove(connection: sqlite3.Connection, key: str) -> None:
        connection.execute("DELETE FROM session_search WHERE session_key = ?", (key,))
        connection.execute("DELETE FROM search_manifest WHERE session_key = ?", (key,))
