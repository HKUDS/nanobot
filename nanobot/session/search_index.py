"""Rebuildable FTS5 candidates over canonical, public session history."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextlib import closing, suppress
from pathlib import Path
from typing import Any, cast

from filelock import FileLock
from loguru import logger

from nanobot.session.manager import SessionManager

_INDEX_FILENAME = ".session_search.sqlite3"
_INDEX_VERSION = 1


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
        rows: list[dict[str, Any]],
        load_content: Callable[[str], str],
    ) -> set[str] | None:
        needle = query.casefold()
        if len(needle) < 3 or "\x00" in needle:
            return None
        try:
            with self._lock:
                if self._path.is_symlink():
                    return None
                for attempt in range(2):
                    try:
                        return self._query(needle, rows, load_content)
                    except sqlite3.DatabaseError as exc:
                        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                        if attempt or code not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                            raise
                        # All connections are closed before removing only our cache.
                        for suffix in ("", "-wal", "-shm"):
                            Path(str(self._path) + suffix).unlink(missing_ok=True)
        except (sqlite3.Error, OSError) as exc:
            logger.debug("Session search cache unavailable; using canonical scan: {}", exc)
        return None

    def _signatures(self, rows: list[dict[str, Any]]) -> dict[str, str] | None:
        versions = self._sessions.list_session_versions()
        signatures: dict[str, str] = {}
        for row in rows:
            key = row.get("key")
            if not isinstance(key, str):
                return None
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
        rows: list[dict[str, Any]],
        load_content: Callable[[str], str],
    ) -> set[str] | None:
        signatures = self._signatures(rows)
        if signatures is None:
            return None
        with closing(sqlite3.connect(self._path, timeout=1)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            with connection:
                self._schema(connection)
                with suppress(OSError):
                    os.chmod(self._path, 0o600)
                indexed = self._reconcile(connection, signatures, load_content)
                hits = self._matches(connection, needle)
        current = self._signatures(rows)
        if current is not None:
            hits.update(key for key in current if current[key] != indexed.get(key))
        return hits

    @staticmethod
    def _matches(connection: sqlite3.Connection, needle: str) -> set[str]:
        phrase = '"' + needle.replace('"', '""') + '"'
        return {
            cast(str, key)
            for (key,) in connection.execute(
                "SELECT manifest.session_key FROM session_search "
                "JOIN search_manifest AS manifest ON manifest.rowid = session_search.rowid "
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
            "CREATE VIRTUAL TABLE session_search USING fts5(content, tokenize = 'trigram')"
        )
        connection.execute(f"PRAGMA user_version = {_INDEX_VERSION}")

    def _reconcile(
        self,
        connection: sqlite3.Connection,
        signatures: dict[str, str],
        load_content: Callable[[str], str],
    ) -> dict[str, str]:
        stored = {
            key: (row_id, signature)
            for row_id, key, signature in cast(
                list[tuple[int, str, str]],
                connection.execute(
                    "SELECT rowid, session_key, signature FROM search_manifest"
                ).fetchall(),
            )
        }
        indexed = {key: signature for key, (_, signature) in stored.items()}
        for key in stored.keys() - signatures.keys():
            self._remove(connection, stored[key][0])
            indexed.pop(key)
        for key, signature in signatures.items():
            previous = stored.get(key)
            if previous is not None and previous[1] == signature:
                continue
            content = load_content(key).replace("\x00", "")
            if self._session_signature(key) != signature:
                # A write raced this read; leave the old entry for the final
                # signature check to route through direct verification.
                continue
            if previous is None:
                cursor = connection.execute(
                    "INSERT INTO search_manifest (session_key, signature) VALUES (?, ?)",
                    (key, signature),
                )
                row_id = cast(int, cursor.lastrowid)
            else:
                row_id = previous[0]
                connection.execute("DELETE FROM session_search WHERE rowid = ?", (row_id,))
                connection.execute(
                    "UPDATE search_manifest SET signature = ? WHERE rowid = ?",
                    (signature, row_id),
                )
            connection.execute(
                "INSERT INTO session_search (rowid, content) VALUES (?, ?)",
                (row_id, content.casefold()),
            )
            indexed[key] = signature
        return indexed

    @staticmethod
    def _remove(connection: sqlite3.Connection, row_id: int) -> None:
        connection.execute("DELETE FROM session_search WHERE rowid = ?", (row_id,))
        connection.execute("DELETE FROM search_manifest WHERE rowid = ?", (row_id,))
