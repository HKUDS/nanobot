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
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from nanobot.observability.tracing import bind_trace

from .._text import _utc_now_iso
from ..event import MemoryEvent, memory_type_for_item

if TYPE_CHECKING:
    from ..db.event_store import EventStore
    from ..embedder import Embedder
    from ..graph.graph import KnowledgeGraph
    from .coercion import EventCoercer
    from .dedup import EventDeduplicator


class EventIngester:
    """Owns the full event write path: coerce -> dedup -> persist -> sync."""

    def __init__(
        self,
        *,
        coercer: EventCoercer,
        dedup: EventDeduplicator,
        graph: KnowledgeGraph | None,
        db: EventStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._coercer = coercer
        self._dedup = dedup
        self._graph = graph
        self._db = db
        self._embedder = embedder

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Read events from EventStore.

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

    def append_events(self, events: Sequence[MemoryEvent]) -> int:
        """Main ingestion entry point: dedup, merge, persist, and sync to vector store.

        Uses targeted SQL queries (PK lookup + FTS5 pre-filtering) instead of
        loading all events into memory.  This fixes the correctness bug where
        events beyond the 100-event read limit were invisible to dedup, and
        scales to 100K+ events.

        Accepts ``MemoryEvent`` objects.  Internally converts to dicts for the
        dedup/merge pipeline which does heavy in-place mutation.
        """
        if not events or self._db is None:
            return 0
        raw_events = [e.to_dict() for e in events]
        t0 = time.monotonic()
        written = 0
        merged = 0
        superseded = 0

        for raw in raw_events:
            # Generate ID if missing (same logic as before)
            event_id = raw.get("id")
            if not event_id:
                summary = str(raw.get("summary", "")).strip()
                if not summary:
                    continue
                event_type = str(raw.get("type", "fact"))
                ts = str(raw.get("timestamp", _utc_now_iso()))
                event_id = self._coercer.build_event_id(event_type, summary, ts)
                raw = {**raw, "id": event_id, "timestamp": ts}
            candidate = self._coercer.ensure_event_provenance(raw)

            # Step 1: Exact ID dedup — O(1) PK lookup
            existing_row = self._db.get_event_by_id(event_id)
            if existing_row is not None:
                existing = self._unpack_event(existing_row)
                existing = self._coercer.ensure_event_provenance(existing)
                merged_event = self._dedup.merge_events(existing, candidate, similarity=1.0)
                self._write_events([merged_event])
                merged += 1
                continue

            # Step 2: Supersession — FTS5 pre-filter then existing logic
            supersession_found = False
            if memory_type_for_item(candidate) == "semantic":
                fts_candidates = self._find_dedup_candidates(candidate, limit=30)
                semantic_candidates = [
                    c
                    for c in fts_candidates
                    if memory_type_for_item(c) == "semantic"
                    and str(c.get("status", "")).lower() != "superseded"
                ]
                if semantic_candidates:
                    superseded_idx = self._dedup.find_semantic_supersession(
                        candidate, semantic_candidates
                    )
                    if superseded_idx is not None:
                        now_iso = _utc_now_iso()
                        sup_event = dict(semantic_candidates[superseded_idx])
                        sup_id = str(sup_event.get("id", ""))
                        sup_event["status"] = "superseded"
                        sup_event["superseded_at"] = now_iso
                        if event_id:
                            sup_event["superseded_by_event_id"] = event_id
                        if sup_id:
                            candidate["supersedes_event_id"] = sup_id
                        candidate["supersedes_at"] = now_iso
                        self._write_events([sup_event, candidate])
                        written += 1
                        superseded += 1
                        supersession_found = True

            # Step 3: Semantic duplicate — FTS5 pre-filter + Jaccard
            if not supersession_found:
                fts_candidates = self._find_dedup_candidates(candidate, limit=30)
                if fts_candidates:
                    dup_idx, dup_score = self._dedup.find_semantic_duplicate(
                        candidate, fts_candidates
                    )
                    if dup_idx is not None:
                        merged_event = self._dedup.merge_events(
                            fts_candidates[dup_idx], candidate, similarity=dup_score
                        )
                        self._write_events([merged_event])
                        merged += 1
                        continue

                # Step 4: New event — no match in any step
                self._write_events([candidate])
                written += 1

        if written <= 0 and merged <= 0:
            return 0

        bind_trace().debug(
            "memory_append | written={} | merged={} | superseded={} | {:.0f}ms",
            written,
            merged,
            superseded,
            (time.monotonic() - t0) * 1000,
        )
        return written

    # ------------------------------------------------------------------
    # Private helpers for targeted dedup
    # ------------------------------------------------------------------

    def _find_dedup_candidates(
        self, candidate: dict[str, Any], limit: int = 30
    ) -> list[dict[str, Any]]:
        """Use FTS5 to find events with overlapping tokens, filtered by type.

        Passes the raw summary text to ``search_fts()`` which handles
        tokenization and FTS5 query building internally.
        """
        if self._db is None:
            return []
        summary = str(candidate.get("summary", ""))
        event_type = str(candidate.get("type", ""))
        query_text = f"{event_type} {summary}".strip()
        if not query_text:
            return []
        fts_results = self._db.search_fts(query_text, k=limit * 2)
        candidates: list[dict[str, Any]] = []
        for row in fts_results:
            event = self._unpack_event(row)
            if str(event.get("type", "")) == event_type:
                candidates.append(self._coercer.ensure_event_provenance(event))
            if len(candidates) >= limit:
                break
        return candidates

    def _unpack_event(self, row: dict[str, Any]) -> dict[str, Any]:
        """Unpack metadata._extra from a raw DB row to top-level keys."""
        import json as _json

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
        return event

    def _write_events(self, events: list[dict[str, Any]]) -> None:
        """Pack metadata extras and persist events to EventStore."""
        import json as _json

        if self._db is None:
            return
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
        for event in events:
            evt_copy = dict(event)
            meta = evt_copy.get("metadata")
            meta = meta if isinstance(meta, dict) else {}
            extras = {k: v for k, v in evt_copy.items() if k not in _db_columns}
            if extras:
                meta = {**meta, "_extra": extras}
            evt_copy["metadata"] = _json.dumps(meta) if meta else None
            evt_copy.setdefault("created_at", evt_copy.get("timestamp", _utc_now_iso()))
            self._db.insert_event(evt_copy, embedding=None)

    async def _ingest_graph_triples(self, events: list[MemoryEvent]) -> int:
        """Feed triples from events into the knowledge graph (async).

        Returns the number of triples ingested.  No-op when graph is disabled.
        """
        if not self._graph or not self._graph.enabled:
            return 0

        from ..graph.ontology_types import Triple

        total = 0
        for event in events:
            raw_triples = event.triples
            if not raw_triples:
                continue
            event_id = event.id
            timestamp = event.timestamp
            triple_dicts = [t.model_dump(mode="python") for t in raw_triples]
            parsed = [Triple.from_dict(t, source_event_id=event_id) for t in triple_dicts]
            parsed = [t for t in parsed if t.subject and t.object]
            if parsed:
                await self._graph.ingest_event_triples(event_id, parsed, timestamp=timestamp)
                total += len(parsed)

        return total
