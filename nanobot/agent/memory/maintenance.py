"""Memory maintenance: reindex, seed, health checks, backend stats.

Extracted from ``MemoryStore`` (Task 5) to isolate infrastructure
maintenance from day-to-day memory operations.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from .helpers import _norm_text, _to_str_list, _utc_now_iso
from .mem0_adapter import _Mem0Adapter
from .persistence import MemoryPersistence

if TYPE_CHECKING:
    from .unified_db import UnifiedMemoryDB

_COUNT_CACHE_TTL: float = 60.0  # seconds — SQLite counts change infrequently (LAN-102)


class MemoryMaintenance:
    """Reindex, seed, health-check, and backend-stats operations.

    Constructor takes collaborators that are already initialised in
    ``MemoryStore.__init__``.
    """

    def __init__(
        self,
        *,
        mem0: _Mem0Adapter,
        persistence: MemoryPersistence,
        rollout: dict[str, Any],
        db: UnifiedMemoryDB | None = None,
    ) -> None:
        self.mem0 = mem0
        self.persistence = persistence
        self.rollout = rollout
        self._db = db

        # TTL caches for SQLite count queries (LAN-102)
        self._vector_count_cache: tuple[float, int] | None = None
        self._history_count_cache: tuple[float, int] | None = None

    # ── mem0 / vector infrastructure ──────────────────────────────────

    def _mem0_get_all_rows(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if not self.mem0.enabled or not self.mem0.client:
            return []
        try:
            raw = self.mem0.client.get_all(user_id=self.mem0.user_id, limit=max(1, limit))
        except TypeError:
            try:
                raw = self.mem0.client.get_all(self.mem0.user_id, max(1, limit))
            except Exception:  # crash-barrier: mem0 SDK produces varied errors
                return []
        except Exception:  # crash-barrier: mem0 SDK produces varied errors
            return []
        return self.mem0._rows(raw)

    def _vector_points_count(self) -> int:
        now = time.monotonic()
        if self._vector_count_cache is not None:
            ts, cached = self._vector_count_cache
            if now - ts < _COUNT_CACHE_TTL:
                return cached
        local_mem0_dir = self.mem0._local_mem0_dir or (self.persistence.memory_dir / "mem0")
        base = local_mem0_dir / "qdrant" / "collection"
        if not base.exists() or not base.is_dir():
            result = 0
            self._vector_count_cache = (now, result)
            return result
        total = 0
        for child in base.iterdir():
            if not child.is_dir():
                continue
            storage = child / "storage.sqlite"
            if not storage.exists():
                continue
            try:
                conn = sqlite3.connect(storage)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM points")
                total += int(cur.fetchone()[0])
                conn.close()
            except (sqlite3.Error, OSError):
                continue
        result = max(total, 0)
        self._vector_count_cache = (now, result)
        return result

    def _history_row_count(self) -> int:
        now = time.monotonic()
        if self._history_count_cache is not None:
            ts, cached = self._history_count_cache
            if now - ts < _COUNT_CACHE_TTL:
                return cached
        local_mem0_dir = self.mem0._local_mem0_dir or (self.persistence.memory_dir / "mem0")
        history_db = local_mem0_dir / "history.db"
        if not history_db.exists():
            self._history_count_cache = (now, 0)
            return 0
        try:
            conn = sqlite3.connect(history_db)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)
                FROM history
                WHERE COALESCE(is_deleted, 0) = 0
                  AND COALESCE(new_memory, '') != ''
                """
            )
            count = int(cur.fetchone()[0])
            conn.close()
            result = max(count, 0)
            self._history_count_cache = (now, result)
            return result
        except (sqlite3.Error, OSError):
            return 0

    def _backend_stats_for_eval(self) -> dict[str, Any]:
        """Collect backend stats needed by EvalRunner.get_observability_report."""
        return {
            "vector_points_count": self._vector_points_count(),
            "mem0_get_all_count": len(self._mem0_get_all_rows(limit=500)),
            "history_rows_count": self._history_row_count(),
            "mem0_enabled": self.mem0.enabled,
            "mem0_mode": self.mem0.mode,
        }

    # ── Health check ──────────────────────────────────────────────────

    async def ensure_health(self) -> None:
        """Run vector health check asynchronously (non-blocking).

        Must be awaited from an async context after instantiation.
        Called by ``AgentLoop.run()`` at startup instead of running
        synchronously in ``__init__`` (LAN-101).
        """
        import asyncio

        await asyncio.to_thread(self._ensure_vector_health)

    def _ensure_vector_health(self) -> None:
        if not bool(self.rollout.get("memory_vector_health_enabled", True)):
            return
        if not self.mem0.enabled:
            return
        vector_rows = len(self._mem0_get_all_rows(limit=25))
        vector_points = self._vector_points_count()
        history_rows = self._history_row_count()
        # Explicit probe — side-effect is health check; result intentionally unused.
        self.mem0.search("__health__", top_k=1, allow_history_fallback=False)
        degraded = history_rows > 0 and vector_rows == 0 and vector_points == 0
        if not degraded:
            return
        if not bool(self.rollout.get("memory_auto_reindex_on_empty_vector", True)):
            return
        # Circular call: MemoryStore wires reindex_from_structured_memory to delegate here,
        # but the health check also needs to trigger reindex.  We use _reindex_fn callback.
        if self._reindex_fn is not None:
            self._reindex_fn()
        else:
            logger.warning("MemoryMaintenance: _reindex_fn not set, skipping auto-reindex")

    # ── Compaction / reindex ──────────────────────────────────────────

    # Set by MemoryStore after construction so health check can trigger reindex.
    _reindex_fn: Any = None

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
        """Full reindex from structured memory into mem0.

        ``read_profile_fn``, ``read_events_fn``, and ``ingester`` are injected
        by ``MemoryStore`` at call-time so this class stays decoupled.
        """
        if self._db is not None:
            # Events are already in SQLite; reindex of events_vec is a
            # future concern.  Return a no-op success result.
            return {
                "ok": True,
                "reason": "unified_db_active",
                "written": 0,
                "failed": 0,
            }

        if not self.mem0.enabled:
            return {"ok": False, "reason": "mem0_disabled", "written": 0, "failed": 0}

        reset_result: dict[str, Any] = {
            "requested": bool(reset_existing),
            "ok": True,
            "reason": "",
            "deleted_estimate": 0,
        }
        if reset_existing:
            ok, reason, deleted_estimate = self.mem0.delete_all_user_memories()
            reset_result = {
                "requested": True,
                "ok": bool(ok),
                "reason": str(reason),
                "deleted_estimate": int(deleted_estimate),
            }
            if not ok:
                return {
                    "ok": False,
                    "reason": "structured_reindex_reset_failed",
                    "written": 0,
                    "failed": 0,
                    "events_indexed": 0,
                    "reset": reset_result,
                }

        profile = read_profile_fn() if read_profile_fn else {}
        events = (
            read_events_fn(
                limit=max_events if isinstance(max_events, int) and max_events > 0 else None
            )
            if read_events_fn
            else []
        )
        compaction_stats = {
            "before": len(events),
            "after": len(events),
            "superseded_dropped": 0,
            "duplicates_dropped": 0,
        }
        if compact:
            events, compaction_stats = self._compact_events_for_reindex(events)
        written = 0
        failed = 0
        seen: set[tuple[str, str, str]] = set()

        section_topic = {
            "preferences": "user_preference",
            "stable_facts": "knowledge",
            "active_projects": "project",
            "relationships": "relationship",
            "constraints": "constraint",
        }
        section_event_type = {
            "preferences": "preference",
            "stable_facts": "fact",
            "active_projects": "fact",
            "relationships": "relationship",
            "constraints": "constraint",
        }

        # Use ingester helpers if available, else fall back to static methods.
        sanitize_text = ingester._sanitize_mem0_text if ingester else lambda t, **kw: t
        sanitize_meta = ingester._sanitize_mem0_metadata if ingester else lambda m: m
        event_write_plan = ingester._event_mem0_write_plan if ingester else lambda e: []

        for section in profile_keys:
            values = profile.get(section, [])
            if not isinstance(values, list):
                continue
            for value in values:
                summary = sanitize_text(str(value), allow_archival=False)
                if not summary:
                    continue
                metadata = sanitize_meta(
                    {
                        "memory_type": "semantic",
                        "topic": section_topic.get(section, "general"),
                        "stability": "high",
                        "source": "profile",
                        "event_type": section_event_type.get(section, "fact"),
                        "status": "active",
                        "timestamp": profile.get("last_verified_at") or _utc_now_iso(),
                    }
                )
                key = (
                    _norm_text(summary),
                    str(metadata.get("memory_type", "")),
                    str(metadata.get("topic", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                if self.mem0.add_text(summary, metadata=metadata):
                    written += 1
                else:
                    failed += 1

        for event in events:
            for text, raw_metadata in event_write_plan(event):
                summary = sanitize_text(
                    text,
                    allow_archival=bool(raw_metadata.get("archival")),
                )
                if not summary:
                    continue
                metadata = sanitize_meta(dict(raw_metadata))
                metadata["source"] = "events"
                key = (
                    _norm_text(summary),
                    str(metadata.get("memory_type", "")),
                    str(metadata.get("topic", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                if self.mem0.add_text(summary, metadata=metadata):
                    written += 1
                else:
                    failed += 1

        flushed = self.mem0.flush_vector_store()
        if flushed:
            self.mem0.reopen_client()

        _vpc = vector_points_count_fn or self._vector_points_count
        _mgar = mem0_get_all_rows_fn or self._mem0_get_all_rows
        vector_points_after = _vpc()
        mem0_rows_after = len(_mgar(limit=500))
        ok = failed == 0 and (vector_points_after > 0 or mem0_rows_after > 0)
        return {
            "ok": ok,
            "reason": "structured_reindex",
            "written": written,
            "failed": failed,
            "events_indexed": len(events),
            "compacted": bool(compact),
            "events_before_compaction": int(compaction_stats.get("before", len(events))),
            "events_after_compaction": int(compaction_stats.get("after", len(events))),
            "events_superseded_dropped": int(compaction_stats.get("superseded_dropped", 0)),
            "events_duplicates_dropped": int(compaction_stats.get("duplicates_dropped", 0)),
            "reset": reset_result,
            "vector_points_after": vector_points_after,
            "mem0_get_all_after": mem0_rows_after,
            "mem0_add_mode": str(self.mem0.last_add_mode),
            "flush_applied": flushed,
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

        events_file = self.persistence.events_file
        self.persistence.write_jsonl(events_file, seeded_events)
        result = self.reindex_from_structured_memory(
            reset_existing=True,
            compact=True,
            read_profile_fn=read_profile_fn,
            read_events_fn=read_events_fn,
            ingester=ingester,
            profile_keys=profile_keys,
            vector_points_count_fn=vector_points_count_fn,
            mem0_get_all_rows_fn=mem0_get_all_rows_fn,
        )
        return {
            "ok": bool(result.get("ok")),
            "reason": "seeded_structured_corpus",
            "seeded_profile_items": sum(
                len(_to_str_list(seeded_profile.get(k))) for k in profile_keys
            ),
            "seeded_events": len(seeded_events),
            "reindex": result,
        }
