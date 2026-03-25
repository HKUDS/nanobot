"""Memory maintenance: reindex, seed, health checks, backend stats.

Extracted from ``MemoryStore`` (Task 5) to isolate infrastructure
maintenance from day-to-day memory operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ._text import _norm_text, _to_str_list, _utc_now_iso

if TYPE_CHECKING:
    from .unified_db import UnifiedMemoryDB


class MemoryMaintenance:
    """Reindex, seed, health-check, and backend-stats operations.

    Constructor takes collaborators that are already initialised in
    ``MemoryStore.__init__``.
    """

    def __init__(
        self,
        *,
        rollout_fn: Callable[[], dict[str, Any]],
        db: UnifiedMemoryDB | None = None,
        reindex_fn: Callable[[], None] | None = None,
    ) -> None:
        self._rollout_fn = rollout_fn
        self._db = db
        self._reindex_fn = reindex_fn

    # ── backend stats ─────────────────────────────────────────────────

    def _backend_stats_for_eval(self) -> dict[str, Any]:
        """Collect backend stats needed by EvalRunner.get_observability_report."""
        if self._db is not None:
            event_count = len(self._db.read_events(limit=500))
        else:
            event_count = 0
        return {
            "vector_points_count": 0,
            "mem0_get_all_count": 0,
            "history_rows_count": 0,
            "mem0_enabled": False,
            "mem0_mode": "disabled",
            "db_event_count": event_count,
        }

    # ── Health check ──────────────────────────────────────────────────

    async def ensure_health(self) -> None:
        """Run health check asynchronously (non-blocking).

        Must be awaited from an async context after instantiation.
        Called by ``AgentLoop.run()`` at startup instead of running
        synchronously in ``__init__`` (LAN-101).
        """
        # With UnifiedMemoryDB, no vector store health check is needed.
        pass

    # ── Compaction / reindex ──────────────────────────────────────────

    @staticmethod
    def _event_compaction_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
        summary = _norm_text(str(event.get("summary", "")))
        event_type = str(event.get("type", "fact")).strip().lower() or "fact"
        memory_type = str(event.get("memory_type", "episodic")).strip().lower() or "episodic"
        topic = str(event.get("topic", "general")).strip().lower() or "general"
        return (summary, event_type, memory_type, topic)

    @staticmethod
    def _compact_events_for_reindex(
        events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        if not events:
            return [], {
                "before": 0,
                "after": 0,
                "superseded_dropped": 0,
                "duplicates_dropped": 0,
            }

        compacted: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        superseded_dropped = 0
        duplicates_dropped = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            status = str(event.get("status", "")).strip().lower()
            if status == "superseded":
                superseded_dropped += 1
                continue
            key = MemoryMaintenance._event_compaction_key(event)
            if not key[0]:
                continue
            existing = compacted.get(key)
            if existing is None:
                compacted[key] = event
                continue
            old_ts = str(existing.get("timestamp", ""))
            new_ts = str(event.get("timestamp", ""))
            if new_ts >= old_ts:
                compacted[key] = event
            duplicates_dropped += 1

        out = sorted(compacted.values(), key=lambda e: str(e.get("timestamp", "")))
        return out, {
            "before": len(events),
            "after": len(out),
            "superseded_dropped": superseded_dropped,
            "duplicates_dropped": duplicates_dropped,
        }

    def reindex_from_structured_memory(
        self,
        *,
        max_events: int | None = None,
        reset_existing: bool = False,
        compact: bool = False,
        read_profile_fn: Any = None,
        read_events_fn: Any = None,
        ingester: Any = None,
        profile_keys: tuple[str, ...] = (
            "preferences",
            "stable_facts",
            "active_projects",
            "relationships",
            "constraints",
        ),
        vector_points_count_fn: Any = None,
        mem0_get_all_rows_fn: Any = None,
    ) -> dict[str, Any]:
        """Full reindex from structured memory.

        With UnifiedMemoryDB, events are already in SQLite; return a no-op
        success result.  Legacy mem0 reindex has been removed.
        """
        return {
            "ok": True,
            "reason": "unified_db_active",
            "written": 0,
            "failed": 0,
        }

    def seed_structured_corpus(
        self,
        *,
        profile_path: Path,
        events_path: Path,
        read_profile_fn: Any = None,
        write_profile_fn: Any = None,
        read_events_fn: Any = None,
        ingester: Any = None,
        profile_keys: tuple[str, ...] = (
            "preferences",
            "stable_facts",
            "active_projects",
            "relationships",
            "constraints",
        ),
        vector_points_count_fn: Any = None,
        mem0_get_all_rows_fn: Any = None,
    ) -> dict[str, Any]:
        """Seed with sample data from external profile + events files."""
        try:
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
            if not isinstance(profile_payload, dict):
                raise ValueError("seed profile must be a JSON object")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            return {"ok": False, "reason": f"invalid_profile_seed:{exc}"}

        seeded_profile = read_profile_fn() if read_profile_fn else {}
        for key in profile_keys:
            incoming = profile_payload.get(key, [])
            if isinstance(incoming, list):
                seeded_profile[key] = [str(x).strip() for x in incoming if str(x).strip()]
            else:
                seeded_profile[key] = []
        conflicts = profile_payload.get("conflicts", [])
        seeded_profile["conflicts"] = conflicts if isinstance(conflicts, list) else []
        seeded_profile["last_verified_at"] = _utc_now_iso()
        seeded_profile["updated_at"] = _utc_now_iso()
        seeded_profile.setdefault("meta", {key: {} for key in profile_keys})
        if write_profile_fn:
            write_profile_fn(seeded_profile)

        seeded_events: list[dict[str, Any]] = []
        coerce_event = ingester._coerce_event if ingester else None
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                text = str(line).strip()
                if not text:
                    continue
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    continue
                if coerce_event:
                    coerced = coerce_event(payload, source_span=[0, 0])
                    if coerced:
                        seeded_events.append(coerced)
        except (json.JSONDecodeError, OSError) as exc:
            return {"ok": False, "reason": f"invalid_events_seed:{exc}"}

        # With UnifiedMemoryDB, events are inserted directly.
        if self._db is not None:
            for event in seeded_events:
                self._db.insert_event(event)

        return {
            "ok": True,
            "reason": "seeded_structured_corpus",
            "seeded_profile_items": sum(
                len(_to_str_list(seeded_profile.get(k))) for k in profile_keys
            ),
            "seeded_events": len(seeded_events),
            "reindex": {
                "ok": True,
                "reason": "unified_db_active",
                "written": 0,
                "failed": 0,
            },
        }
