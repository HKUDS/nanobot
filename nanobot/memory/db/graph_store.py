"""GraphStore -- entity/edge CRUD and BFS neighbor traversal.

Operates on the ``entities`` and ``edges`` tables inside the shared
SQLite database managed by :class:`MemoryDatabase`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["GraphStore"]


class GraphStore:
    """Entity and edge CRUD with BFS neighbor traversal.

    Operates on the entities and edges tables.
    Receives a shared SQLite connection from MemoryDatabase.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Graph entities
    # ------------------------------------------------------------------

    def upsert_entity(
        self,
        name: str,
        *,
        type: str = "unknown",
        aliases: str = "",
        properties: str = "{}",
        first_seen: str = "",
        last_seen: str = "",
    ) -> None:
        """Insert or update a graph entity."""
        with self._conn:
            self._conn.execute(
                """INSERT INTO entities (name, type, aliases, properties, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       type = excluded.type,
                       aliases = excluded.aliases,
                       properties = excluded.properties,
                       last_seen = excluded.last_seen""",
                (name, type, aliases, properties, first_seen, last_seen),
            )

    def get_entity(self, name: str) -> dict[str, Any] | None:
        """Get an entity by name. Returns None if not found."""
        row = self._conn.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def search_entities(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Search entities by name or alias substring match."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """SELECT * FROM entities
               WHERE name LIKE ? OR aliases LIKE ?
               ORDER BY name LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Graph edges
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source: str,
        target: str,
        *,
        relation: str,
        confidence: float = 0.7,
        event_id: str = "",
        timestamp: str = "",
    ) -> None:
        """Add or update a directed edge between entities."""
        with self._conn:
            self._conn.execute(
                """INSERT INTO edges (source, target, relation, confidence, event_id, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source, relation, target) DO UPDATE SET
                       confidence = MAX(excluded.confidence, edges.confidence),
                       event_id = excluded.event_id,
                       timestamp = excluded.timestamp""",
                (source, target, relation, confidence, event_id, timestamp),
            )

    def get_edges_from(self, entity_name: str) -> list[dict[str, Any]]:
        """Get all outgoing edges from an entity."""
        rows = self._conn.execute("SELECT * FROM edges WHERE source = ?", (entity_name,)).fetchall()
        return [dict(row) for row in rows]

    def get_edges_to(self, entity_name: str) -> list[dict[str, Any]]:
        """Get all incoming edges to an entity."""
        rows = self._conn.execute("SELECT * FROM edges WHERE target = ?", (entity_name,)).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_neighbors(self, entity_name: str, *, depth: int = 1) -> list[dict[str, Any]]:
        """BFS neighbor traversal up to *depth* hops via recursive CTE.

        Returns entities reachable from *entity_name* (both directions).
        """
        depth = max(1, min(depth, 5))  # clamp
        rows = self._conn.execute(
            """WITH RECURSIVE bfs(name, d) AS (
                   VALUES(?, 0)
                   UNION
                   SELECT CASE WHEN e.source = bfs.name THEN e.target
                               ELSE e.source END,
                          bfs.d + 1
                   FROM bfs
                   JOIN edges e ON e.source = bfs.name OR e.target = bfs.name
                   WHERE bfs.d < ?
               )
               SELECT DISTINCT ent.*
               FROM bfs
               JOIN entities ent ON ent.name = bfs.name
               WHERE bfs.name != ?""",
            (entity_name, depth, entity_name),
        ).fetchall()
        return [dict(row) for row in rows]
