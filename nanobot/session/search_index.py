"""Rebuildable FTS5 candidates over canonical, public session history."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, cast

from filelock import FileLock
from loguru import logger

from nanobot.session.manager import SessionManager

_INDEX_FILENAME = ".session_search.sqlite3"
_INDEX_VERSION = 1


class SessionSearchIndex:
    """Select candidates; the reader owns visibility, ordering and excerpts.

    A separate cache lock serializes SQLite access and corruption recovery.
    Canonical files are locked only for snapshots and individual content reads,
    allowing session saves while SQLite builds the index. Files changed during
    indexing are returned as candidates for the reader to check directly.
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
            paths = self._paths(rows)
            if paths is None:
                return None
            with self._lock:
                if self._path.is_symlink():
                    return None
                for attempt in range(2):
                    try:
                        return self._query(needle, paths, load_content)
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

    def _paths(self, rows: list[dict[str, Any]]) -> dict[str, Path] | None:
        paths: dict[str, Path] = {}
        for row in rows:
            key = row.get("key")
            if not isinstance(key, str):
                return None
            path = self._sessions.canonical_session_path(key)
            if path is None:
                return None
            paths[key] = path
        return paths

    @staticmethod
    def _signature(path: Path) -> str | None:
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        return f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"

    def _signatures(self, paths: dict[str, Path]) -> dict[str, str]:
        with self._sessions.locked_session_files():
            return {
                key: signature
                for key, path in paths.items()
                if (signature := self._signature(path)) is not None
            }

    def _query(
        self,
        needle: str,
        paths: dict[str, Path],
        load_content: Callable[[str], str],
    ) -> set[str]:
        signatures = self._signatures(paths)
        with closing(sqlite3.connect(self._path, timeout=1)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            with connection:
                self._schema(connection)
                indexed = self._reconcile(connection, signatures, paths, load_content)
                hits = self._matches(connection, needle)
        current = self._signatures(paths)
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
        paths: dict[str, Path],
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
            with self._sessions.locked_session_files():
                content = load_content(key).casefold()
                signature = self._signature(paths[key])
            if signature is None:
                if previous is not None:
                    self._remove(connection, previous[0])
                    indexed.pop(key)
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
                (row_id, content),
            )
            indexed[key] = signature
        return indexed

    @staticmethod
    def _remove(connection: sqlite3.Connection, row_id: int) -> None:
        connection.execute("DELETE FROM session_search WHERE rowid = ?", (row_id,))
        connection.execute("DELETE FROM search_manifest WHERE rowid = ?", (row_id,))
