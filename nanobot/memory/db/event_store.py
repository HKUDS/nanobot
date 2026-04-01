"""EventStore -- event CRUD, FTS5 keyword search, and vector KNN search.

Operates on the events, events_fts, and events_vec tables.
Receives a shared SQLite connection from MemoryDatabase.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import sqlite_vec  # type: ignore[import-untyped]

from .._text import _utc_now_iso

__all__ = ["EventStore"]


class EventStore:
    """Event CRUD, FTS5 keyword search, and vector KNN search.

    Operates on the events, events_fts, and events_vec tables.
    Receives a shared SQLite connection from MemoryDatabase.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def insert_event(
        self,
        event: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> None:
        """Insert an event with optional vector embedding (single transaction)."""
        # Auto-serialize metadata dict -> JSON string for the TEXT column.
        raw_meta = event.get("metadata")
        if isinstance(raw_meta, dict):
            raw_meta = json.dumps(raw_meta)
        with self._conn:
            # Clean up any existing vector entry before replace (rowid changes
            # on INSERT OR REPLACE)
            old_row = self._conn.execute(
                "SELECT rowid FROM events WHERE id = ?", (event["id"],)
            ).fetchone()
            if old_row is not None:
                self._conn.execute("DELETE FROM events_vec WHERE id = ?", (old_row[0],))
            self._conn.execute(
                """INSERT OR REPLACE INTO events
                   (id, type, summary, timestamp, source, status, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["id"],
                    event["type"],
                    event["summary"],
                    event["timestamp"],
                    event.get("source"),
                    event.get("status", "active"),
                    raw_meta,
                    event.get("created_at", event.get("timestamp", _utc_now_iso())),
                ),
            )
            if embedding is not None:
                rowid = self._conn.execute(
                    "SELECT rowid FROM events WHERE id = ?", (event["id"],)
                ).fetchone()[0]
                self._conn.execute(
                    "INSERT OR REPLACE INTO events_vec (id, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(embedding)),
                )

    def get_event_by_id(self, event_id: str) -> dict[str, Any] | None:
        """Fetch a single event by primary key. Returns None if not found."""
        row = self._conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def read_events(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read events ordered by timestamp descending."""
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if type:
            clauses.append("type = ?")
            params.append(type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM events{where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_vector(
        self,
        query_embedding: list[float],
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """KNN vector search via sqlite-vec. Returns events with distance."""
        rows = self._conn.execute(
            """SELECT e.*, v.distance
               FROM events_vec v
               JOIN events e ON e.rowid = v.id
               WHERE v.embedding MATCH ?
               AND k = ?
               ORDER BY v.distance""",
            (sqlite_vec.serialize_float32(query_embedding), k),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_fts(self, query_text: str, k: int = 10) -> list[dict[str, Any]]:
        """FTS5 keyword search over event summaries.

        Uses term-level matching (implicit AND) rather than phrase matching
        so that "coffee preference" matches documents containing both terms
        anywhere, not just the exact phrase.
        """
        # Quote each term individually to escape FTS5 operators.
        # Use OR logic so that any matching term returns results.
        terms = re.findall(r"\w+", query_text)
        if not terms:
            return []
        # Use prefix matching (t*) so "deploy" matches "deployment" and vice versa.
        # FTS5 does exact token matching -- no stemming -- so prefix helps recall.
        safe_query = " OR ".join(f"{t}*" for t in terms)
        try:
            rows = self._conn.execute(
                """SELECT e.*, rank
                   FROM events_fts fts
                   JOIN events e ON e.rowid = fts.rowid
                   WHERE events_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, k),
            ).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS query -- return empty
            return []
        return [dict(row) for row in rows]

    def search_by_metadata(
        self,
        *,
        topic: str | None = None,
        memory_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Fallback search by event type and/or metadata topic."""
        conditions: list[str] = []
        params: list[Any] = []
        if memory_type:
            conditions.append("type = ?")
            params.append(memory_type)
        if topic:
            conditions.append("json_extract(metadata, '$.topic') = ?")
            params.append(topic)
        if not conditions:
            return []
        where = " AND ".join(conditions)
        params.append(k)
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
