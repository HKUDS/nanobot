"""Event ingestion pipeline for the memory subsystem.

``EventIngester`` is a thin orchestrator that delegates to focused collaborators:

- ``EventClassifier`` — memory-type classification, metadata enrichment
- ``EventCoercer`` — event normalization and ID generation
- ``EventDeduplicator`` — duplicate/supersession detection and merging

It retains only the top-level ``append_events`` / ``read_events`` entry points
and knowledge-graph triple ingestion.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from nanobot.observability.tracing import bind_trace

from .._text import _utc_now_iso
from .classification import EVENT_TYPES, MEMORY_STABILITY, MEMORY_TYPES
from .coercion import EPISODIC_STATUS_OPEN, EPISODIC_STATUS_RESOLVED

if TYPE_CHECKING:
    from ..embedder import Embedder
    from ..graph.graph import KnowledgeGraph
    from ..unified_db import UnifiedMemoryDB
    from .coercion import EventCoercer
    from .dedup import EventDeduplicator


class EventIngester:
    """Owns the full event write path: coerce -> dedup -> persist -> sync."""

    # Class-level aliases for backward compatibility.
    EVENT_TYPES = EVENT_TYPES
    MEMORY_TYPES = MEMORY_TYPES
    MEMORY_STABILITY = MEMORY_STABILITY
    EPISODIC_STATUS_OPEN = EPISODIC_STATUS_OPEN
    EPISODIC_STATUS_RESOLVED = EPISODIC_STATUS_RESOLVED

    def __init__(
        self,
        *,
        coercer: EventCoercer,
        dedup: EventDeduplicator,
        graph: KnowledgeGraph | None,
        db: UnifiedMemoryDB | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._coercer = coercer
        self._dedup = dedup
        self._graph = graph
        self._db = db
        self._embedder = embedder

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Read events from UnifiedMemoryDB.

        Extra fields packed into metadata._extra on write are unpacked back
        to top-level keys so callers see the same dict shape as was stored.
        """
        if self._db is not None:
            import json as _json

            rows = self._db.read_events(limit=limit or 100)
            result: list[dict[str, Any]] = []
            for row in rows:
                event = dict(row)
                raw_meta = event.get("metadata")
                if isinstance(raw_meta, str):
                    try:
                        meta = _json.loads(raw_meta)
                    except (ValueError, TypeError):
                        meta = {}
                else:
                    meta = raw_meta if isinstance(raw_meta, dict) else {}
                extras = meta.pop("_extra", None) if isinstance(meta, dict) else None
                if isinstance(extras, dict):
                    event.update(extras)
                if meta:
                    event["metadata"] = meta
                result.append(event)
            return result
        return []

    def append_events(self, events: list[dict[str, Any]]) -> int:
        """Main ingestion entry point: dedup, merge, persist, and sync to vector store."""
        if not events:
            return 0
        t0_append = time.monotonic()
        existing_events = [
            self._coercer.ensure_event_provenance(event) for event in self.read_events()
        ]
        existing_ids = {e.get("id") for e in existing_events if e.get("id")}
        written = 0
        merged = 0
        superseded = 0
        appended_events: list[dict[str, Any]] = []

        for raw in events:
            event_id = raw.get("id")
            if not event_id:
                # Auto-generate ID for events without one (mirrors coerce_event).
                summary = str(raw.get("summary", "")).strip()
                if not summary:
                    continue
                event_type = str(raw.get("type", "fact"))
                ts = str(raw.get("timestamp", _utc_now_iso()))
                event_id = self._coercer.build_event_id(event_type, summary, ts)
                raw = {**raw, "id": event_id, "timestamp": ts}
            candidate = self._coercer.ensure_event_provenance(raw)

            if event_id in existing_ids:
                for idx, existing in enumerate(existing_events):
                    if existing.get("id") == event_id:
                        existing_events[idx] = self._dedup.merge_events(
                            existing, candidate, similarity=1.0
                        )
                        merged += 1
                        break
                continue

            superseded_idx = self._dedup.find_semantic_supersession(candidate, existing_events)
            if superseded_idx is not None:
                now_iso = _utc_now_iso()
                superseded_event = dict(existing_events[superseded_idx])
                superseded_id = str(superseded_event.get("id", "")).strip()
                superseded_event["status"] = "superseded"
                superseded_event["superseded_at"] = now_iso
                if event_id:
                    superseded_event["superseded_by_event_id"] = event_id
                existing_events[superseded_idx] = superseded_event
                if superseded_id:
                    candidate["supersedes_event_id"] = superseded_id
                candidate["supersedes_at"] = now_iso
                existing_ids.add(event_id)
                existing_events.append(candidate)
                appended_events.append(candidate)
                written += 1
                superseded += 1
                continue

            dup_idx, dup_score = self._dedup.find_semantic_duplicate(candidate, existing_events)
            if dup_idx is not None:
                existing_events[dup_idx] = self._dedup.merge_events(
                    existing_events[dup_idx], candidate, similarity=dup_score
                )
                merged += 1
                continue

            existing_ids.add(event_id)
            existing_events.append(candidate)
            appended_events.append(candidate)
            written += 1

        if written <= 0 and merged <= 0:
            return 0

        # Write to UnifiedMemoryDB
        if self._db is not None:
            import json as _json

            # Collect all events that need writing: newly appended or modified
            # (merged/superseded). Use existing_events which has the final state
            # after all in-memory merges.
            appended_ids = {a.get("id") for a in appended_events}
            events_to_write = [
                e
                for e in existing_events
                if e.get("id") in appended_ids
                or e.get("merged_event_count", 1) > 1
                or e.get("status") == "superseded"
            ]

            for event in events_to_write:
                # Events are inserted without embeddings in the sync write path.
                # Embeddings are backfilled by maintenance.reindex() or by the
                # caller via db.insert_event() with a pre-computed embedding.
                embedding = None
                # Pack extra fields (entities, triples, confidence, salience,
                # source_span, etc.) into metadata JSON so they survive the
                # SQLite round-trip through the fixed-column events table.
                evt_copy = dict(event)
                _db_columns = {
                    "id",
                    "type",
                    "summary",
                    "timestamp",
                    "source",
                    "status",
                    "metadata",
                    "created_at",
                }
                meta = evt_copy.get("metadata")
                meta = meta if isinstance(meta, dict) else {}
                extras = {k: v for k, v in evt_copy.items() if k not in _db_columns}
                if extras:
                    meta = {**meta, "_extra": extras}
                evt_copy["metadata"] = _json.dumps(meta) if meta else None
                evt_copy.setdefault("created_at", evt_copy.get("timestamp", _utc_now_iso()))
                self._db.insert_event(evt_copy, embedding=embedding)
        bind_trace().debug(
            "memory_append | written={} | merged={} | superseded={} | {:.0f}ms",
            written,
            merged,
            superseded,
            (time.monotonic() - t0_append) * 1000,
        )
        return written

    async def _ingest_graph_triples(self, events: list[dict[str, Any]]) -> int:
        """Feed triples from events into the knowledge graph (async).

        Returns the number of triples ingested.  No-op when graph is disabled.
        """
        if not self._graph or not self._graph.enabled:
            return 0

        from ..graph.ontology_types import Triple

        total = 0
        for event in events:
            raw_triples = event.get("triples")
            if not isinstance(raw_triples, list) or not raw_triples:
                continue
            event_id = str(event.get("id", ""))
            timestamp = str(event.get("timestamp", ""))
            parsed = [Triple.from_dict(t, source_event_id=event_id) for t in raw_triples]
            parsed = [t for t in parsed if t.subject and t.object]
            if parsed:
                await self._graph.ingest_event_triples(event_id, parsed, timestamp=timestamp)
                total += len(parsed)

        return total
