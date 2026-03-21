"""mem0-first memory store with structured profile/events maintenance.

This is the **primary public API** for all memory operations.  ``MemoryStore``
orchestrates the full lifecycle:

1. **Retrieval** — queries mem0 vector store first; falls back to local
   keyword search (``retrieval.py``) when mem0 is unavailable; optionally
   re-ranks results via cross-encoder (``reranker.py``).
2. **Consolidation** — after each conversation turn, extracts structured
   events via ``MemoryExtractor``, persists them through
   ``MemoryPersistence``, and updates ``MEMORY.md`` / ``profile.json``.
3. **Compaction** — periodic LLM-driven merge of redundant events and
   profile contradiction resolution.

All file I/O is delegated to ``MemoryPersistence``; all vector operations
go through ``_Mem0Adapter``.  This module owns the coordination logic only.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.prompt_loader import prompts
from nanobot.agent.tracing import bind_trace

from .conflicts import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    ConflictManager,
)
from .constants import _SAVE_MEMORY_TOOL
from .context_assembler import ContextAssembler
from .eval import EvalRunner
from .extractor import MemoryExtractor
from .graph import KnowledgeGraph
from .helpers import (
    _GRAPH_QUERY_STOPWORDS,
    _contains_any,
    _estimate_tokens,
    _extract_query_keywords,
    _norm_text,
    _safe_float,
    _to_datetime,
    _to_str_list,
    _tokenize,
    _utc_now_iso,
)
from .ingester import EventIngester
from .mem0_adapter import _Mem0Adapter, _Mem0RuntimeInfo
from .persistence import MemoryPersistence
from .profile import ProfileManager
from .reranker import CompositeReranker, Reranker
from .retrieval import _local_retrieve, _topic_fallback_retrieve
from .retrieval_planner import RetrievalPlanner
from .rollout import RolloutConfig

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session

_COUNT_CACHE_TTL: float = 60.0  # seconds — SQLite counts change infrequently (LAN-102)


class MemoryStore:
    """mem0-first memory store with structured profile/events maintenance."""

    PROFILE_KEYS = (
        "preferences",
        "stable_facts",
        "active_projects",
        "relationships",
        "constraints",
    )
    EVENT_TYPES = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    MEMORY_TYPES = {"semantic", "episodic", "reflection"}
    MEMORY_STABILITY = {"high", "medium", "low"}
    PROFILE_STATUS_ACTIVE = "active"
    PROFILE_STATUS_CONFLICTED = "conflicted"
    PROFILE_STATUS_STALE = "stale"
    CONFLICT_STATUS_OPEN = CONFLICT_STATUS_OPEN
    CONFLICT_STATUS_NEEDS_USER = CONFLICT_STATUS_NEEDS_USER
    CONFLICT_STATUS_RESOLVED = CONFLICT_STATUS_RESOLVED
    EPISODIC_STATUS_OPEN = "open"
    EPISODIC_STATUS_RESOLVED = "resolved"
    ROLLOUT_MODES = RolloutConfig.ROLLOUT_MODES  # backward compat alias

    def __init__(
        self,
        workspace: Path,
        rollout_overrides: dict[str, Any] | None = None,
        *,
        embedding_provider: str | None = None,
        vector_backend: str | None = None,
    ):
        self.workspace = workspace
        self.persistence = MemoryPersistence(workspace)
        self.memory_dir = self.persistence.memory_dir
        self.memory_file = self.persistence.memory_file
        self.history_file = self.persistence.history_file
        self.events_file = self.persistence.events_file
        self.profile_file = self.persistence.profile_file
        self.index_dir: Path = self.memory_dir / "index"
        self.retriever = _Mem0RuntimeInfo()
        # EventIngester is constructed after persistence/mem0/graph are ready.
        # Deferred until graph is built below; placeholder here for type checkers.
        self.ingester: EventIngester  # set after graph init

        self.extractor = MemoryExtractor(
            to_str_list=_to_str_list,
            coerce_event=lambda raw, **kw: self.ingester._coerce_event(raw, **kw),
            utc_now_iso=_utc_now_iso,
        )
        self._rollout_config = RolloutConfig(overrides=rollout_overrides)
        self.rollout = self._rollout_config.rollout  # backward compat dict reference
        self.mem0 = _Mem0Adapter(
            workspace=workspace,
            user_id=str(self.rollout.get("mem0_user_id", "nanobot")),
            add_debug=bool(self.rollout.get("mem0_add_debug", False)),
            verify_write=bool(self.rollout.get("mem0_verify_write", True)),
            force_infer_true=bool(self.rollout.get("mem0_force_infer_true", False)),
        )

        # Profile manager (LAN-202) — delegates profile CRUD to ProfileManager.
        self.profile_mgr = ProfileManager(self.persistence, self.profile_file, self.mem0)
        self.profile_mgr._store = self

        # Conflict manager (LAN-203) — delegates conflict resolution to ConflictManager.
        self.conflict_mgr = ConflictManager(self.profile_mgr, self.mem0)
        self.conflict_mgr._store = self

        # Retrieval planner (LAN-207) — intent classification + policy + routing.
        self._planner = RetrievalPlanner()

        # Context assembler (LAN-210) — prompt rendering extracted from MemoryStore.
        self._assembler = ContextAssembler(
            profile_mgr=self.profile_mgr,
            retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw),
            persistence=self.persistence,
            planner=self._planner,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            read_long_term_fn=lambda: self.read_long_term(),
            build_graph_context_lines_fn=self._build_graph_context_lines,
        )

        # _ensure_vector_health() moved to async ensure_health() — called from
        # AgentLoop.run() to avoid blocking the event loop at instantiation (LAN-101).

        # TTL caches for SQLite count queries — avoids re-opening connections on every call (LAN-102)
        self._vector_count_cache: tuple[float, int] | None = None
        self._history_count_cache: tuple[float, int] | None = None

        # Cross-encoder re-ranker (Step 7)
        reranker_model = str(
            self.rollout.get("reranker_model", "onnx:ms-marco-MiniLM-L-6-v2")
        ).strip()
        reranker_alpha = float(self.rollout.get("reranker_alpha", 0.5))
        self._reranker: Reranker
        if reranker_model.startswith("onnx:"):
            from .onnx_reranker import OnnxCrossEncoderReranker

            self._reranker = OnnxCrossEncoderReranker(
                model_name=reranker_model.split(":", 1)[1], alpha=reranker_alpha
            )
        else:
            self._reranker = CompositeReranker(alpha=reranker_alpha)

        # Knowledge graph (networkx + JSON persistence).
        graph_enabled = self.rollout.get("graph_enabled", False)
        if graph_enabled:
            self.graph = KnowledgeGraph(workspace=workspace)
        else:
            self.graph = KnowledgeGraph()  # disabled — all methods return empty

        # EventIngester: owns the full event write path.
        self.ingester = EventIngester(
            persistence=self.persistence,
            mem0=self.mem0,
            graph=self.graph,
            rollout=self.rollout,
            conflict_pair_fn=lambda old, new: self.profile_mgr._conflict_pair(old, new),
        )

        # LAN-208: gate raw conversation turn ingestion into mem0.
        # When disabled, only structured events (from extractor) are synced to mem0,
        # clarifying mem0's role as a semantic index rather than a raw transcript store.
        self._mem0_raw_turn_ingestion: bool = bool(
            self.rollout.get("mem0_raw_turn_ingestion", True)
        )

        # Configurable auto-resolve confidence gap threshold.
        self.conflict_auto_resolve_gap: float = float(
            self.rollout.get("conflict_auto_resolve_gap", 0.25)
        )
        self.conflict_mgr.conflict_auto_resolve_gap = self.conflict_auto_resolve_gap

        # P-01/P-02: mtime-based cache for events.jsonl — avoids re-reading the
        # file on every BM25 retrieval call within the same turn.
        self._events_cache: list[dict[str, Any]] | None = None
        self._events_cache_mtime: float = -1.0

        # Evaluation / observability helper (LAN-204)
        # Use lambdas so that test-time MagicMock patches on the instance are honoured.
        self._eval = EvalRunner(
            retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw),
            persistence=self.persistence,
            workspace=self.workspace,
            get_rollout_status_fn=lambda: self.get_rollout_status(),
            get_rollout_fn=lambda: self.rollout,
            get_backend_stats_fn=lambda: self._backend_stats_for_eval(),
        )

    # -- Shared helpers imported from .helpers --------------------------------
    # Kept as class attributes for backward compatibility with any external
    # callers that use ``MemoryStore._utc_now_iso()`` etc.
    _utc_now_iso = staticmethod(_utc_now_iso)
    _safe_float = staticmethod(_safe_float)
    _norm_text = staticmethod(_norm_text)
    _tokenize = staticmethod(_tokenize)
    _GRAPH_QUERY_STOPWORDS = _GRAPH_QUERY_STOPWORDS
    _extract_query_keywords = staticmethod(_extract_query_keywords)  # type: ignore[assignment]
    _to_str_list = staticmethod(_to_str_list)
    _to_datetime = staticmethod(_to_datetime)
    _estimate_tokens = staticmethod(_estimate_tokens)

    def get_rollout_status(self) -> dict[str, Any]:
        """Return a snapshot of the current rollout config (delegates to RolloutConfig)."""
        return self._rollout_config.get_status()

    _contains_any = staticmethod(_contains_any)

    # ── Thin wrappers delegating to RetrievalPlanner (LAN-207) ──────────

    @staticmethod
    def _infer_retrieval_intent(query: str) -> str:
        return RetrievalPlanner.infer_retrieval_intent(query)

    @staticmethod
    def _retrieval_policy(intent: str) -> dict[str, Any]:
        return RetrievalPlanner.retrieval_policy(intent)

    @staticmethod
    def _query_routing_hints(query: str) -> dict[str, Any]:
        return RetrievalPlanner.query_routing_hints(query)

    def _status_matches_query_hint(
        self,
        *,
        status: str,
        summary: str,
        requires_open: bool,
        requires_resolved: bool,
    ) -> bool:
        return RetrievalPlanner.status_matches_query_hint(
            status=status,
            summary=summary,
            requires_open=requires_open,
            requires_resolved=requires_resolved,
        )

    def _memory_type_for_item(self, item: dict[str, Any]) -> str:
        return RetrievalPlanner.memory_type_for_item(item)

    def _recency_signal(self, timestamp: str, *, half_life_days: float) -> float:
        return RetrievalPlanner.recency_signal(timestamp, half_life_days=half_life_days)

    # Temporary aliases — will be removed in Task 7
    def _default_topic_for_event_type(self, event_type: str) -> str:
        return self.ingester._default_topic_for_event_type(event_type)

    def _classify_memory_type(
        self, *, event_type: str, summary: str, source: str
    ) -> tuple[str, str, bool]:
        return self.ingester._classify_memory_type(
            event_type=event_type, summary=summary, source=source
        )

    def _distill_semantic_summary(self, summary: str) -> str:
        return self.ingester._distill_semantic_summary(summary)

    def _normalize_memory_metadata(
        self,
        metadata: dict[str, Any] | None,
        *,
        event_type: str,
        summary: str,
        source: str,
    ) -> tuple[dict[str, Any], bool]:
        return self.ingester._normalize_memory_metadata(
            metadata, event_type=event_type, summary=summary, source=source
        )

    def _event_mem0_write_plan(self, event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return self.ingester._event_mem0_write_plan(event)

    @staticmethod
    def _looks_blob_like_summary(summary: str) -> bool:
        return EventIngester._looks_blob_like_summary(summary)

    @staticmethod
    def _sanitize_mem0_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        return EventIngester._sanitize_mem0_metadata(metadata)

    def _sanitize_mem0_text(self, text: str, *, allow_archival: bool = False) -> str:
        return self.ingester._sanitize_mem0_text(text, allow_archival=allow_archival)

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
        local_mem0_dir = self.mem0._local_mem0_dir or (self.workspace / "memory" / "mem0")
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
        local_mem0_dir = self.mem0._local_mem0_dir or (self.workspace / "memory" / "mem0")
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

    def _event_compaction_key(self, event: dict[str, Any]) -> tuple[str, str, str, str]:
        summary = self._norm_text(str(event.get("summary", "")))
        event_type = str(event.get("type", "fact")).strip().lower() or "fact"
        memory_type = str(event.get("memory_type", "episodic")).strip().lower() or "episodic"
        topic = str(event.get("topic", "general")).strip().lower() or "general"
        return (summary, event_type, memory_type, topic)

    def _compact_events_for_reindex(
        self, events: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        if not events:
            return [], {"before": 0, "after": 0, "superseded_dropped": 0, "duplicates_dropped": 0}

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
            key = self._event_compaction_key(event)
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
    ) -> dict[str, Any]:
        if not self.mem0.enabled:
            result = {"ok": False, "reason": "mem0_disabled", "written": 0, "failed": 0}
            return result

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
                result = {
                    "ok": False,
                    "reason": "structured_reindex_reset_failed",
                    "written": 0,
                    "failed": 0,
                    "events_indexed": 0,
                    "reset": reset_result,
                }
                return result

        profile = self.read_profile()
        events = self.ingester.read_events(
            limit=max_events if isinstance(max_events, int) and max_events > 0 else None
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

        for section in self.PROFILE_KEYS:
            values = profile.get(section, [])
            if not isinstance(values, list):
                continue
            for value in values:
                summary = self.ingester._sanitize_mem0_text(str(value), allow_archival=False)
                if not summary:
                    continue
                metadata = self.ingester._sanitize_mem0_metadata(
                    {
                        "memory_type": "semantic",
                        "topic": section_topic.get(section, "general"),
                        "stability": "high",
                        "source": "profile",
                        "event_type": section_event_type.get(section, "fact"),
                        "status": "active",
                        "timestamp": profile.get("last_verified_at") or self._utc_now_iso(),
                    }
                )
                key = (
                    self._norm_text(summary),
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
            for text, raw_metadata in self._event_mem0_write_plan(event):
                summary = self._sanitize_mem0_text(
                    text,
                    allow_archival=bool(raw_metadata.get("archival")),
                )
                if not summary:
                    continue
                metadata = self._sanitize_mem0_metadata(dict(raw_metadata))
                metadata["source"] = "events"
                key = (
                    self._norm_text(summary),
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

        vector_points_after = self._vector_points_count()
        mem0_rows_after = len(self._mem0_get_all_rows(limit=500))
        ok = failed == 0 and (vector_points_after > 0 or mem0_rows_after > 0)
        result = {
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
        return result

    def seed_structured_corpus(self, *, profile_path: Path, events_path: Path) -> dict[str, Any]:
        try:
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
            if not isinstance(profile_payload, dict):
                raise ValueError("seed profile must be a JSON object")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            return {"ok": False, "reason": f"invalid_profile_seed:{exc}"}

        seeded_profile = self.read_profile()
        for key in self.PROFILE_KEYS:
            incoming = profile_payload.get(key, [])
            if isinstance(incoming, list):
                seeded_profile[key] = [str(x).strip() for x in incoming if str(x).strip()]
            else:
                seeded_profile[key] = []
        conflicts = profile_payload.get("conflicts", [])
        seeded_profile["conflicts"] = conflicts if isinstance(conflicts, list) else []
        seeded_profile["last_verified_at"] = self._utc_now_iso()
        seeded_profile["updated_at"] = self._utc_now_iso()
        seeded_profile.setdefault("meta", {key: {} for key in self.PROFILE_KEYS})
        self.write_profile(seeded_profile)

        seeded_events: list[dict[str, Any]] = []
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                text = str(line).strip()
                if not text:
                    continue
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    continue
                coerced = self.ingester._coerce_event(payload, source_span=[0, 0])
                if coerced:
                    seeded_events.append(coerced)
        except (json.JSONDecodeError, OSError) as exc:
            return {"ok": False, "reason": f"invalid_events_seed:{exc}"}

        self.persistence.write_jsonl(self.events_file, seeded_events)
        result = self.reindex_from_structured_memory(reset_existing=True, compact=True)
        return {
            "ok": bool(result.get("ok")),
            "reason": "seeded_structured_corpus",
            "seeded_profile_items": sum(
                len(self._to_str_list(seeded_profile.get(k))) for k in self.PROFILE_KEYS
            ),
            "seeded_events": len(seeded_events),
            "reindex": result,
        }

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
        # Explicit probe requested in rollout plan.
        _probe_result = self.mem0.search("__health__", top_k=1, allow_history_fallback=False)
        degraded = history_rows > 0 and vector_rows == 0 and vector_points == 0
        if not degraded:
            return
        if not bool(self.rollout.get("memory_auto_reindex_on_empty_vector", True)):
            return
        self.reindex_from_structured_memory()

    def get_observability_report(self) -> dict[str, Any]:
        """Return backend health and rollout status.

        Legacy per-counter metrics have been removed in favour of Langfuse.
        The ``metrics`` and ``kpis`` keys are kept empty for backward
        compatibility with callers that destructure the return value.
        """
        return self._eval.get_observability_report()

    def evaluate_retrieval_cases(
        self,
        cases: list[dict[str, Any]],
        *,
        default_top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality using labeled cases."""
        return self._eval.evaluate_retrieval_cases(
            cases,
            default_top_k=default_top_k,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
        )

    def save_evaluation_report(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
        *,
        rollout: dict[str, Any] | None = None,
        output_file: str | None = None,
    ) -> Path:
        """Persist evaluation + observability report to disk and return the file path."""
        return self._eval.save_evaluation_report(
            evaluation,
            observability,
            rollout=rollout,
            output_file=output_file,
        )

    def evaluate_rollout_gates(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
    ) -> dict[str, Any]:
        return self._eval.evaluate_rollout_gates(evaluation, observability)

    # Temporary aliases — will be removed in Task 7
    def read_events(self, **kw: Any) -> list[dict[str, Any]]:
        return self.ingester.read_events(**kw)

    @staticmethod
    def _merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
        return EventIngester._merge_source_span(base, incoming)

    def _ensure_event_provenance(self, event: dict[str, Any]) -> dict[str, Any]:
        return self.ingester._ensure_event_provenance(event)

    def _event_similarity(self, left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
        return self.ingester._event_similarity(left, right)

    def _find_semantic_duplicate(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> tuple[int | None, float]:
        return self.ingester._find_semantic_duplicate(candidate, existing_events)

    def _find_semantic_supersession(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> int | None:
        return self.ingester._find_semantic_supersession(candidate, existing_events)

    def _merge_events(
        self,
        base: dict[str, Any],
        incoming: dict[str, Any],
        *,
        similarity: float,
    ) -> dict[str, Any]:
        return self.ingester._merge_events(base, incoming, similarity=similarity)

    def append_events(self, events: list[dict[str, Any]]) -> int:
        return self.ingester.append_events(events)

    # Temporary alias — will be removed in Task 7
    async def _ingest_graph_triples(self, events: list[dict[str, Any]]) -> int:
        return await self.ingester._ingest_graph_triples(events)

    def read_profile(self) -> dict[str, Any]:
        return self.profile_mgr.read_profile()

    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]:
        return self.profile_mgr._meta_section(profile, key)

    @staticmethod
    def _generate_belief_id(section: str, norm_text: str, created_at: str) -> str:
        """Generate a deterministic stable ID for a profile item."""
        return ProfileManager._generate_belief_id(section, norm_text, created_at)

    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]:
        return self.profile_mgr._meta_entry(profile, key, text)

    _MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.

    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = 0.05,
        max_confidence: float = 0.99,
        status: str | None = None,
        evidence_event_id: str | None = None,
    ) -> None:
        self.profile_mgr._touch_meta_entry(
            entry,
            confidence_delta=confidence_delta,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            status=status,
            evidence_event_id=evidence_event_id,
        )

    def _validate_profile_field(self, field: str) -> str:
        return self.profile_mgr._validate_profile_field(field)

    def set_item_pin(self, field: str, text: str, *, pinned: bool) -> bool:
        return self.profile_mgr.set_item_pin(field, text, pinned=pinned)

    def mark_item_outdated(self, field: str, text: str) -> bool:
        return self.profile_mgr.mark_item_outdated(field, text)

    def list_conflicts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        return self.conflict_mgr.list_conflicts(include_closed=include_closed)

    @staticmethod
    def _parse_conflict_user_action(text: str) -> str | None:
        return ConflictManager._parse_conflict_user_action(text)

    # Language patterns indicating a correction (new value supersedes old).
    _CORRECTION_MARKERS = ConflictManager._CORRECTION_MARKERS

    def _auto_resolution_action(self, conflict: dict[str, Any]) -> str | None:
        return self.conflict_mgr._auto_resolution_action(conflict)

    def auto_resolve_conflicts(self, *, max_items: int = 10) -> dict[str, int]:
        return self.conflict_mgr.auto_resolve_conflicts(max_items=max_items)

    def get_next_user_conflict(self) -> dict[str, Any] | None:
        return self.conflict_mgr.get_next_user_conflict()

    def _conflict_relevant_to(self, conflict: dict[str, Any], user_message: str) -> bool:
        return self.conflict_mgr._conflict_relevant_to(conflict, user_message)

    def ask_user_for_conflict(
        self,
        *,
        include_already_asked: bool = False,
        user_message: str = "",
    ) -> str | None:
        return self.conflict_mgr.ask_user_for_conflict(
            include_already_asked=include_already_asked,
            user_message=user_message,
        )

    def handle_user_conflict_reply(self, text: str) -> dict[str, Any]:
        return self.conflict_mgr.handle_user_conflict_reply(text)

    def resolve_conflict_details(self, index: int, action: str) -> dict[str, Any]:
        return self.conflict_mgr.resolve_conflict_details(index, action)

    def resolve_conflict(self, index: int, action: str) -> bool:
        return self.conflict_mgr.resolve_conflict(index, action)

    def write_profile(self, profile: dict[str, Any]) -> None:
        self.profile_mgr.write_profile(profile)

    def _build_event_id(self, event_type: str, summary: str, timestamp: str) -> str:
        return self.ingester._build_event_id(event_type, summary, timestamp)

    def _infer_episodic_status(
        self, *, event_type: str, summary: str, raw_status: Any = None
    ) -> str | None:
        return self.ingester._infer_episodic_status(
            event_type=event_type, summary=summary, raw_status=raw_status
        )

    def _coerce_event(
        self,
        raw: dict[str, Any],
        *,
        source_span: list[int],
        channel: str = "",
        chat_id: str = "",
    ) -> dict[str, Any] | None:
        return self.ingester._coerce_event(
            raw, source_span=source_span, channel=channel, chat_id=chat_id
        )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        # Local BM25 retrieval with intent routing when mem0 is unavailable.
        if not self.mem0.enabled:
            events = self.ingester.read_events()
            plan = self._planner.plan(query)
            policy = plan.policy
            candidate_k = max(1, min(top_k * int(policy.get("candidate_multiplier", 3)), 60))
            half_life = recency_half_life_days or float(policy.get("half_life_days", 60.0))

            wants_superseded = plan.include_superseded

            # Graph query augmentation: expand search terms with related entities.
            augmented_query = query
            if self.graph.enabled:
                query_keywords = self._extract_query_keywords(query)
                if query_keywords:
                    graph_related = self.graph.get_related_entity_names_sync(
                        query_keywords,
                        depth=2,
                    )
                    # Append related entity names to the query for BM25 matching.
                    extra_terms = graph_related - query_keywords
                    if extra_terms:
                        augmented_query = (
                            query
                            + " "
                            + " ".join(t.replace("-", " ").replace("_", " ") for t in extra_terms)
                        )

            candidates = _local_retrieve(
                events,
                augmented_query,
                top_k=candidate_k,
                recency_half_life_days=half_life,
                include_superseded=wants_superseded,
            )

            # Topic-based fallback: fill remaining slots when BM25 yields few matches.
            bm25_ids = {str(c.get("id", "")) for c in candidates}
            fallback_topics = list(policy.get("fallback_topics", []))
            fallback_types = list(policy.get("fallback_types", []))
            remaining = max(0, candidate_k - len(candidates))
            if remaining > 0 and (fallback_topics or fallback_types):
                fallback = _topic_fallback_retrieve(
                    events,
                    target_topics=fallback_topics,
                    target_memory_types=fallback_types,
                    exclude_ids=bm25_ids,
                    top_k=remaining,
                    base_score=0.25,
                    include_superseded=wants_superseded,
                )
                candidates.extend(fallback)

            # Apply intent-based type boosts and metadata enrichment.
            graph_boost = 0.15 if self.graph.enabled else 0.0
            query_entities = {e.lower() for e in self.extractor._extract_entities(query)}
            graph_entity_names: set[str] = set()
            if graph_boost > 0 and query_entities:
                # Collect entity names related to query entities from event triples.
                for evt in events:
                    for triple in evt.get("triples") or []:
                        subj = str(triple.get("subject", "")).lower()
                        obj = str(triple.get("object", "")).lower()
                        if subj in query_entities:
                            graph_entity_names.add(obj)
                        elif obj in query_entities:
                            graph_entity_names.add(subj)
                # Augment with graph neighbors when available.
                graph_related = self.graph.get_related_entity_names_sync(
                    query_entities,
                    depth=2,
                )
                graph_entity_names |= graph_related

            for item in candidates:
                memory_type = self._memory_type_for_item(item)
                item["memory_type"] = memory_type
                # Promote metadata fields to top level for downstream consumers.
                meta = item.get("metadata", {})
                if not item.get("topic"):
                    item["topic"] = str(meta.get("topic", "")).strip()
                if not item.get("stability"):
                    item["stability"] = str(meta.get("stability", "medium")).strip()
                base_score = float(item.get("retrieval_reason", {}).get("score", 0.0))
                type_boost = float(policy.get("type_boost", {}).get(memory_type, 0.0))
                stability = str(item.get("stability", "medium")).lower()
                stability_boost = {"high": 0.03, "medium": 0.01, "low": -0.02}.get(stability, 0.0)
                # Graph expansion boost: boost events that mention entities
                # related to query entities via the knowledge graph.
                g_boost = 0.0
                if graph_entity_names:
                    item_entities = {
                        e.lower() for e in (item.get("entities") or []) if isinstance(e, str)
                    }
                    if item_entities & graph_entity_names:
                        g_boost = graph_boost
                item["score"] = base_score + type_boost + stability_boost + g_boost
            candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            results = candidates[:top_k]
            bind_trace().debug(
                "Memory retrieve source=bm25 results={} duration_ms={:.0f}",
                len(results),
                (time.monotonic() - t0) * 1000,
            )
            return results

        mode = str(self.rollout.get("memory_rollout_mode", "enabled")).strip().lower()
        if mode not in self.ROLLOUT_MODES:
            mode = "enabled"
        type_separation_enabled = bool(self.rollout.get("memory_type_separation_enabled", True))
        router_enabled = bool(self.rollout.get("memory_router_enabled", True))
        reflection_enabled = bool(self.rollout.get("memory_reflection_enabled", True))
        if mode == "disabled":
            type_separation_enabled = False
            router_enabled = False
            reflection_enabled = False
        if mode == "shadow":
            router_enabled = False

        final, stats = self._retrieve_core(
            query=query,
            top_k=top_k,
            router_enabled=router_enabled,
            type_separation_enabled=type_separation_enabled,
            reflection_enabled=reflection_enabled,
        )

        shadow_enabled = bool(self.rollout.get("memory_shadow_mode", False))
        shadow_rate = float(self.rollout.get("memory_shadow_sample_rate", 0.2) or 0.0)
        if shadow_enabled and shadow_rate > 0 and mode != "disabled":
            shadow_should_run = shadow_rate >= 1.0 or (hash(f"{query}|{top_k}") % 1000) < int(
                shadow_rate * 1000
            )
            if shadow_should_run:
                shadow_router_enabled = not router_enabled
                shadow_final, _ = self._retrieve_core(
                    query=query,
                    top_k=top_k,
                    router_enabled=shadow_router_enabled,
                    type_separation_enabled=type_separation_enabled,
                    reflection_enabled=reflection_enabled,
                )
                primary_ids = {
                    str(item.get("id", "")) for item in final if str(item.get("id", "")).strip()
                }
                shadow_ids = {
                    str(item.get("id", ""))
                    for item in shadow_final
                    if str(item.get("id", "")).strip()
                }
                if primary_ids or shadow_ids:
                    overlap = len(primary_ids & shadow_ids) / max(len(primary_ids | shadow_ids), 1)
                    bind_trace().debug(
                        "Shadow retrieve overlap={:.2f} primary={} shadow={}",
                        overlap,
                        len(primary_ids),
                        len(shadow_ids),
                    )
        bind_trace().debug(
            "Memory retrieve source=mem0 results={} intent={} duration_ms={:.0f}",
            len(final),
            stats["intent"],
            (time.monotonic() - t0) * 1000,
        )
        return final

    def _retrieve_core(
        self,
        *,
        query: str,
        top_k: int,
        router_enabled: bool,
        type_separation_enabled: bool,
        reflection_enabled: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        planner = RetrievalPlanner(
            router_enabled=router_enabled,
            type_separation_enabled=type_separation_enabled,
        )
        plan = planner.plan(query)
        intent = plan.intent
        policy = plan.policy
        candidate_multiplier = (
            max(int(policy.get("candidate_multiplier", 3)), 1) if router_enabled else 1
        )
        candidate_k = max(1, min(max(top_k, top_k * candidate_multiplier), 60))
        allowed_sources = {
            str(item).strip().lower()
            for item in self.rollout.get("memory_fallback_allowed_sources", [])
            if str(item).strip()
        }
        max_summary_chars = int(self.rollout.get("memory_fallback_max_summary_chars", 280) or 280)

        # Compute graph-expanded terms (used for supplementary BM25 pass below).
        graph_extra_terms: set[str] = set()
        if self.graph.enabled:
            query_keywords = self._extract_query_keywords(query)
            if query_keywords:
                graph_related = self.graph.get_related_entity_names_sync(
                    query_keywords,
                    depth=2,
                )
                graph_extra_terms = graph_related - query_keywords

        search_result = self.mem0.search(
            query,
            top_k=candidate_k,
            allow_get_all_fallback=True,
            allow_history_fallback=bool(self.rollout.get("memory_history_fallback_enabled", False)),
            allowed_sources=allowed_sources,
            max_summary_chars=max_summary_chars,
            reject_blob_like=True,
            return_stats=True,
        )
        if isinstance(search_result, tuple) and len(search_result) == 2:
            retrieved, source_stats = search_result
        else:
            retrieved = search_result if isinstance(search_result, list) else []
            source_stats = {
                "source_vector": 0,
                "source_get_all": 0,
                "source_history": 0,
                "rejected_blob_like": 0,
            }
        if intent == "rollout_status":
            retrieved.append(
                {
                    "id": "rollout_status_snapshot",
                    "timestamp": self._utc_now_iso(),
                    "type": "fact",
                    "summary": (
                        "Memory rollout status: "
                        f"mode={self.rollout.get('memory_rollout_mode')}, "
                        f"router={self.rollout.get('memory_router_enabled')}, "
                        f"shadow={self.rollout.get('memory_shadow_mode')}, "
                        f"reflection={self.rollout.get('memory_reflection_enabled')}, "
                        f"type_separation={self.rollout.get('memory_type_separation_enabled')}."
                    ),
                    "entities": [],
                    "score": 0.95,
                    "memory_type": "semantic",
                    "topic": "rollout",
                    "stability": "high",
                    "source": "config",
                    "confidence": 1.0,
                    "evidence_refs": [],
                    "retrieval_reason": {
                        "provider": "nanobot",
                        "backend": "synthetic_rollout",
                        "semantic": 0.95,
                        "recency": 0.0,
                    },
                    "provenance": {"canonical_id": "rollout_status_snapshot", "source_span": None},
                }
            )

        # Supplementary BM25 pass: pull in events matching graph-related entities
        # that mem0 vector search may have missed.
        if graph_extra_terms and retrieved is not None:
            retrieved_ids = {str(r.get("id", "")) for r in retrieved}
            graph_query = (
                query
                + " "
                + " ".join(t.replace("-", " ").replace("_", " ") for t in graph_extra_terms)
            )
            events = self.ingester.read_events()
            bm25_supplement = _local_retrieve(
                events,
                graph_query,
                top_k=candidate_k,
                recency_half_life_days=float(policy.get("half_life_days", 60.0)),
                include_superseded=False,
            )
            for item in bm25_supplement:
                eid = str(item.get("id", ""))
                if eid and eid not in retrieved_ids:
                    # Mark source as graph-augmented BM25
                    reason = item.get("retrieval_reason", {})
                    if not isinstance(reason, dict):
                        reason = {}
                    reason["provider"] = "bm25_graph"
                    item["retrieval_reason"] = reason
                    retrieved.append(item)
                    retrieved_ids.add(eid)

        if not retrieved:
            return [], {
                "intent": intent,
                "retrieved_count": 0,
                "counts": {
                    "retrieval_returned": 0,
                    "retrieval_source_vector_count": int(source_stats.get("source_vector", 0)),
                    "retrieval_source_get_all_count": int(source_stats.get("source_get_all", 0)),
                    "retrieval_source_history_count": int(source_stats.get("source_history", 0)),
                    "retrieval_rejected_blob_count": int(source_stats.get("rejected_blob_like", 0)),
                },
            }

        profile = self.read_profile()
        conflicts = (
            profile.get("conflicts", []) if isinstance(profile.get("conflicts"), list) else []
        )

        field_by_event_type = {
            "preference": "preferences",
            "fact": "stable_facts",
            "relationship": "relationships",
            "constraint": "constraints",
            "task": "active_projects",
            "decision": "active_projects",
        }
        resolved_keep_new_old: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        resolved_keep_new_new: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            if str(conflict.get("status", "")).lower() != "resolved":
                continue
            if str(conflict.get("resolution", "")).lower() != "keep_new":
                continue
            field = str(conflict.get("field", ""))
            if field not in resolved_keep_new_old:
                continue
            old_value = str(conflict.get("old", "")).strip()
            new_value = str(conflict.get("new", "")).strip()
            if old_value:
                resolved_keep_new_old[field].add(self._norm_text(old_value))
            if new_value:
                resolved_keep_new_new[field].add(self._norm_text(new_value))

        def _contains_norm_phrase(text: str, phrase_norm: str) -> bool:
            if not phrase_norm:
                return False
            text_norm = self._norm_text(text)
            if not text_norm:
                return False
            return phrase_norm in text_norm

        adjusted: list[dict[str, Any]] = []
        reflection_filtered_non_reflection_intent = 0
        reflection_filtered_no_evidence = 0
        routing_hints = plan.routing_hints
        for item in retrieved:
            event_type = str(item.get("type", "fact"))
            memory_type = self._memory_type_for_item(item)
            item["memory_type"] = memory_type

            topic = str(item.get("topic", "")).strip().lower()
            summary = str(item.get("summary", ""))
            event_status = str(item.get("status", "")).strip().lower()
            task_or_decision_like = event_type in {"task", "decision", "relationship"} or topic in {
                "task_progress",
                "project",
                "planning",
                "relationship",
            }
            planning_like = task_or_decision_like or self._contains_any(
                summary, ("plan", "next step", "roadmap", "milestone")
            )
            architecture_like = (
                "architecture" in topic
                or self._contains_any(
                    summary, ("architecture", "design decision", "memory architecture")
                )
                or event_type == "decision"
            )
            if (
                routing_hints["focus_task_decision"]
                and not task_or_decision_like
                and intent != "debug_history"
            ):
                continue
            if routing_hints["focus_planning"] and not planning_like:
                continue
            if routing_hints["focus_architecture"] and not architecture_like:
                continue
            if not self._status_matches_query_hint(
                status=event_status,
                summary=summary,
                requires_open=bool(routing_hints["requires_open"]),
                # debug_history needs the full timeline (failures + resolutions).
                requires_resolved=(
                    bool(routing_hints["requires_resolved"]) and intent != "debug_history"
                ),
            ):
                continue
            if intent == "constraints_lookup":
                if memory_type != "semantic":
                    continue
                if "constraint" not in topic and not self._contains_any(
                    summary, ("must", "cannot", "constraint", "should not")
                ):
                    continue
            if intent == "debug_history":
                if memory_type != "episodic" and topic not in {
                    "infra",
                    "task_progress",
                    "incident",
                }:
                    continue
            if intent == "conflict_review":
                if not self._contains_any(
                    summary, ("conflict", "needs_user", "resolved", "keep_new", "decision")
                ):
                    continue
            if intent == "rollout_status":
                if not self._contains_any(
                    summary, ("rollout", "router", "shadow", "reflection", "type_separation")
                ):
                    continue

            if reflection_enabled:
                if (
                    memory_type == "reflection"
                    and type_separation_enabled
                    and intent != "reflection"
                ):
                    reflection_filtered_non_reflection_intent += 1
                    continue
                evidence_refs = item.get("evidence_refs")
                if memory_type == "reflection" and not (
                    isinstance(evidence_refs, list) and len(evidence_refs) > 0
                ):
                    reflection_filtered_no_evidence += 1
                    continue
            elif memory_type == "reflection":
                reflection_filtered_non_reflection_intent += 1
                continue

            field = field_by_event_type.get(event_type)  # type: ignore[assignment]
            summary = str(item.get("summary", ""))
            score = float(item.get("score", 0.0))
            adjustment = 0.0
            adjustment_reasons: list[str] = []
            if field:
                for old_norm in resolved_keep_new_old.get(field, set()):
                    if _contains_norm_phrase(summary, old_norm):
                        adjustment -= 0.18
                        adjustment_reasons.append("resolved_keep_new_old_penalty")
                        break
                for new_norm in resolved_keep_new_new.get(field, set()):
                    if _contains_norm_phrase(summary, new_norm):
                        adjustment += 0.12
                        adjustment_reasons.append("resolved_keep_new_new_boost")
                        break
                section_meta = self._meta_section(profile, field)
                if isinstance(section_meta, dict):
                    for norm_key, meta in section_meta.items():
                        if not isinstance(meta, dict):
                            continue
                        if not _contains_norm_phrase(summary, str(norm_key)):
                            continue
                        status = str(meta.get("status", "")).lower()
                        pinned = bool(meta.get("pinned"))
                        if status == self.PROFILE_STATUS_STALE and not pinned:
                            adjustment -= 0.08
                            adjustment_reasons.append("stale_profile_penalty")
                            break
                        if status == self.PROFILE_STATUS_CONFLICTED:
                            adjustment -= 0.05
                            adjustment_reasons.append("conflicted_profile_penalty")
                            break
            if memory_type == "semantic":
                if (
                    event_status == "superseded"
                    or str(item.get("superseded_by_event_id", "")).strip()
                ):
                    adjustment -= 0.2
                    adjustment_reasons.append("semantic_superseded_penalty")

            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            if adjustment_reasons:
                reason["profile_adjustment"] = round(adjustment, 4)
                reason["profile_adjustment_reasons"] = adjustment_reasons

            recency = self._recency_signal(
                str(item.get("timestamp", "")),
                half_life_days=float(policy.get("half_life_days", 60.0)),
            )
            type_boost = (
                float(policy.get("type_boost", {}).get(memory_type, 0.0))
                if type_separation_enabled
                else 0.0
            )
            stability = str(item.get("stability", "medium")).strip().lower()
            stability_boost = {"high": 0.03, "medium": 0.01, "low": -0.02}.get(stability, 0.0)
            reflection_penalty = -0.06 if memory_type == "reflection" else 0.0
            if not router_enabled:
                recency = 0.0
                stability_boost = 0.0
                reflection_penalty = 0.0
                type_boost = 0.0
            elif reflection_penalty:
                adjustment_reasons.append("reflection_default_penalty")
            intent_bonus = type_boost + (0.08 * recency) + stability_boost + reflection_penalty
            item["score"] = score + adjustment + intent_bonus
            reason["recency"] = round(recency, 4)
            reason["intent"] = intent
            reason["type_boost"] = round(type_boost, 4)
            reason["stability_boost"] = round(stability_boost, 4)
            if reflection_penalty:
                reason["reflection_penalty"] = round(reflection_penalty, 4)
            adjusted.append(item)

        # ------------------------------------------------------------------
        # Cross-encoder re-ranking (Step 7)
        # ------------------------------------------------------------------
        reranker_mode = str(self.rollout.get("reranker_mode", "disabled")).strip().lower()
        if reranker_mode in ("enabled", "shadow") and adjusted:
            if reranker_mode == "enabled":
                adjusted = self._reranker.rerank(query, adjusted)
            else:
                # Shadow: compute re-ranked order but keep heuristic order.
                import copy

                shadow_items = copy.deepcopy(adjusted)
                shadow_items = self._reranker.rerank(query, shadow_items)
                heuristic_ids = [str(it.get("id", "")) for it in adjusted]
                reranked_ids = [str(it.get("id", "")) for it in shadow_items]
                _delta = self._reranker.compute_rank_delta(heuristic_ids, reranked_ids)

        adjusted.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        final = adjusted[: max(1, top_k)]
        counts = {
            "retrieval_returned": len(final),
            "retrieval_filtered_out": max(len(retrieved) - len(final), 0),
            "retrieval_source_vector_count": int(source_stats.get("source_vector", 0)),
            "retrieval_source_get_all_count": int(source_stats.get("source_get_all", 0)),
            "retrieval_source_history_count": int(source_stats.get("source_history", 0)),
            "retrieval_rejected_blob_count": int(source_stats.get("rejected_blob_like", 0)),
            "reflection_filtered_non_reflection_intent": reflection_filtered_non_reflection_intent,
            "reflection_filtered_no_evidence": reflection_filtered_no_evidence,
            "retrieval_returned_semantic": 0,
            "retrieval_returned_episodic": 0,
            "retrieval_returned_reflection": 0,
            "retrieval_returned_unknown": 0,
        }
        for item in final:
            memory_type = str(item.get("memory_type", "")).strip().lower()
            if memory_type == "semantic":
                counts["retrieval_returned_semantic"] += 1
            elif memory_type == "episodic":
                counts["retrieval_returned_episodic"] += 1
            elif memory_type == "reflection":
                counts["retrieval_returned_reflection"] += 1
            else:
                counts["retrieval_returned_unknown"] += 1
        return final, {"intent": intent, "retrieved_count": len(retrieved), "counts": counts}

    # ------------------------------------------------------------------
    # Query entity extraction via entity-index lookup
    # ------------------------------------------------------------------

    def _build_entity_index(self, events: list[dict[str, Any]]) -> set[str]:
        """Collect all unique entity strings from events into a lowercase set."""
        index: set[str] = set()
        for evt in events:
            for e in evt.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    index.add(e.strip().lower())
        return index

    def _extract_query_entities(
        self,
        query: str,
        entity_index: set[str],
    ) -> set[str]:
        """Extract entities from a query by matching tokens against known entities.

        Complements the capitalization-based ``_extract_entities`` by handling
        lowercase queries like "who are alice and bob".  Matches unigrams and
        bigrams against the entity index built from events.
        """
        words = re.findall(r"[a-z0-9][\w-]*", query.lower())
        matched: set[str] = set()
        for w in words:
            if w in entity_index:
                matched.add(w)
        # Also check bigrams (e.g. "github actions", "knowledge graph")
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in entity_index:
                matched.add(bigram)
        return matched

    def _build_graph_context_lines(
        self,
        query: str,
        retrieved: list[dict[str, Any]],
        max_tokens: int = 100,
    ) -> list[str]:
        """Build entity relationship summary lines from graph and local event triples.

        Queries the knowledge graph first (when available), then falls back to
        scanning triples stored in local events.
        """
        query_entities = {e.lower() for e in self.extractor._extract_entities(query)}

        # Also extract entities via index lookup (handles lowercase queries).
        events = self.ingester.read_events(limit=200)
        entity_index = self._build_entity_index(events)
        query_entities |= self._extract_query_entities(query, entity_index)

        for item in retrieved:
            for e in item.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    query_entities.add(e.strip().lower())

        if not query_entities:
            return []

        # Collect relevant triples — graph first, then local event fallback.
        rel_triples: list[tuple[str, str, str]] = []

        if self.graph.enabled:
            rel_triples.extend(self.graph.get_triples_for_entities_sync(query_entities))

        # Supplement with local event triples (may add context the graph lacks).
        for evt in events:
            for triple in evt.get("triples") or []:
                subj = str(triple.get("subject", "")).strip()
                pred = str(triple.get("predicate", "")).strip()
                obj = str(triple.get("object", "")).strip()
                if not subj or not pred or not obj:
                    continue
                if subj.lower() in query_entities or obj.lower() in query_entities:
                    rel_triples.append((subj, pred, obj))

        if not rel_triples:
            return []

        # Deduplicate and format as compact lines, respecting token budget.
        # Annotate entities with ontology types to help the LLM disambiguate.
        from .ontology import classify_entity_type

        seen: set[tuple[str, str, str]] = set()
        graph_lines: list[str] = []
        total_chars = 0
        max_chars = max_tokens * 4

        for subj, pred, obj in rel_triples:
            key = (subj.lower(), pred, obj.lower())
            if key in seen:
                continue
            seen.add(key)
            s_type = classify_entity_type(subj).value
            o_type = classify_entity_type(obj).value
            s_label = f"{subj} [{s_type}]" if s_type != "unknown" else subj
            o_label = f"{obj} [{o_type}]" if o_type != "unknown" else obj
            line = f"- {s_label} → {pred} → {o_label}"
            if total_chars + len(line) > max_chars:
                break
            graph_lines.append(line)
            total_chars += len(line)

        return graph_lines

    def _profile_section_lines(
        self, profile: dict[str, Any], max_items_per_section: int = 6
    ) -> list[str]:
        return self._assembler._profile_section_lines(profile, max_items_per_section)

    @staticmethod
    def _is_resolved_task_or_decision(summary: str) -> bool:
        return ContextAssembler._is_resolved_task_or_decision(summary)

    def _recent_unresolved(
        self, events: list[dict[str, Any]], max_items: int = 8
    ) -> list[dict[str, Any]]:
        return self._assembler._recent_unresolved(events, max_items)

    @staticmethod
    def _memory_item_line(item: dict[str, Any]) -> str:
        return ContextAssembler._memory_item_line(item)

    # ------------------------------------------------------------------
    # MEMORY.md capping (Step 5) — delegates to ContextAssembler (LAN-210)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_md_sections(text: str) -> list[tuple[str, str]]:
        """Split markdown text into (heading, body) pairs.

        Sections are delimited by ``## `` headings.  Text before the first
        heading is returned with heading ``""``.
        """
        return ContextAssembler._split_md_sections(text)

    def _cap_long_term_text(
        self,
        long_term_text: str,
        token_cap: int,
        query: str,
    ) -> str:
        """Return *long_term_text* capped to *token_cap* tokens."""
        return self._assembler._cap_long_term_text(long_term_text, token_cap, query)

    def _fit_lines_to_token_cap(self, lines: list[str], *, token_cap: int) -> list[str]:
        return self._assembler._fit_lines_to_token_cap(lines, token_cap=token_cap)

    # ------------------------------------------------------------------
    # Budget-aware context section allocation — delegates to ContextAssembler
    # ------------------------------------------------------------------

    # Keep class-level constants as aliases so test code referencing
    # MemoryStore._SECTION_PRIORITY_WEIGHTS / ._SECTION_MIN_TOKENS still works.
    _SECTION_PRIORITY_WEIGHTS = ContextAssembler._SECTION_PRIORITY_WEIGHTS
    _SECTION_MIN_TOKENS = ContextAssembler._SECTION_MIN_TOKENS

    @classmethod
    def _allocate_section_budgets(
        cls,
        total_budget: int,
        intent: str,
        section_sizes: dict[str, int],
    ) -> dict[str, int]:
        """Distribute *total_budget* tokens across named sections."""
        return ContextAssembler._allocate_section_budgets(total_budget, intent, section_sizes)

    def _ensure_assembler(self) -> ContextAssembler:
        """Return a ``ContextAssembler``, creating it lazily if needed.

        Lazy creation supports test code that constructs ``MemoryStore`` via
        ``__new__`` (bypassing ``__init__``) and then monkeypatches methods
        before calling ``get_memory_context``.

        All patchable helper methods are routed through lambdas that capture
        ``self``, so monkeypatches applied to the store instance are always
        honoured — even when applied after the assembler is first created.
        """
        # Fast path: already initialised (either by __init__ or a previous call).
        assembler = getattr(self, "_assembler", None)
        if isinstance(assembler, ContextAssembler):
            return assembler

        # Use getattr for attrs that may be missing when __init__ was bypassed
        # (e.g. test code using MemoryStore.__new__).
        profile_mgr = getattr(self, "profile_mgr", None)
        persistence = getattr(self, "persistence", None)
        planner = getattr(self, "_planner", None) or RetrievalPlanner()

        self._assembler = ContextAssembler(
            profile_mgr=profile_mgr,  # type: ignore[arg-type]
            retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw),
            persistence=persistence,  # type: ignore[arg-type]
            planner=planner,
            read_events_fn=lambda **kw: self.read_events(**kw),
            read_long_term_fn=lambda: self.read_long_term(),
            build_graph_context_lines_fn=lambda *a, **kw: self._build_graph_context_lines(*a, **kw),
            cap_long_term_text_fn=lambda text, cap, query: self._cap_long_term_text(
                text, cap, query
            ),
            profile_section_lines_fn=lambda profile, *a: self._profile_section_lines(profile, *a),
            read_profile_fn=lambda: self.read_profile(),
        )
        return self._assembler

    def get_memory_context(
        self,
        *,
        query: str | None = None,
        retrieval_k: int = 6,
        token_budget: int = 900,
        memory_md_token_cap: int = 1500,
        mode: str | None = None,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> str:
        return self._ensure_assembler().build(
            query=query,
            retrieval_k=retrieval_k,
            token_budget=token_budget,
            memory_md_token_cap=memory_md_token_cap,
            mode=mode,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
        )

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        return self.profile_mgr._conflict_pair(old_value, new_value)

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
        source_event_ids: list[str] | None = None,
    ) -> tuple[int, int, int]:
        return self.profile_mgr._apply_profile_updates(
            profile,
            updates,
            enable_contradiction_check=enable_contradiction_check,
            source_event_ids=source_event_ids,
        )

    def _has_open_conflict(
        self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str
    ) -> bool:
        return self.profile_mgr._has_open_conflict(
            profile, field=field, old_value=old_value, new_value=new_value
        )

    def _find_mem0_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        return self.profile_mgr._find_mem0_id_for_text(text, top_k=top_k)

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        return self.profile_mgr.apply_live_user_correction(
            content,
            channel=channel,
            chat_id=chat_id,
            enable_contradiction_check=enable_contradiction_check,
        )

    def read_long_term(self) -> str:
        return self.persistence.read_text(self.memory_file)

    def write_long_term(self, content: str) -> None:
        self.persistence.write_text(self.memory_file, content)

    def append_history(self, entry: str) -> None:
        self.persistence.append_text(self.history_file, entry.rstrip() + "\n\n")

    def rebuild_memory_snapshot(self, *, max_events: int = 30, write: bool = True) -> str:
        profile = self.read_profile()
        events = self.ingester.read_events(limit=max_events)

        # Preserve user-pinned sections across rebuilds (LAN-199 / LAN-206).
        existing_memory = self.read_long_term()
        pinned = self._extract_pinned_section(existing_memory) if existing_memory else None

        parts = ["# Memory", ""]
        section_lines = self._profile_section_lines(profile, max_items_per_section=8)
        if section_lines:
            parts.extend(section_lines)

        unresolved = self._recent_unresolved(events, max_items=6)
        if unresolved:
            parts.append("## Open Tasks & Decisions")
            for event in unresolved:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'task')}) {event.get('summary', '')}")
            parts.append("")

        if events:
            parts.append("## Recent Episodic Highlights")
            for event in events[-max_events:]:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'fact')}) {event.get('summary', '')}")
        snapshot = "\n".join(parts).strip() + "\n"

        if pinned:
            snapshot = self._restore_pinned_section(snapshot, pinned)

        if write:
            self.write_long_term(snapshot)
        return snapshot

    def verify_memory(
        self, *, stale_days: int = 90, update_profile: bool = False
    ) -> dict[str, Any]:
        profile = self.read_profile()
        events = self.ingester.read_events()
        now = datetime.now(timezone.utc)
        stale = 0
        total_ttl = 0
        for event in events:
            ttl_days = event.get("ttl_days")
            timestamp = self._to_datetime(str(event.get("timestamp", "")))
            if not timestamp:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_days = (now - timestamp).total_seconds() / 86400.0
            if isinstance(ttl_days, int) and ttl_days > 0:
                total_ttl += 1
                if age_days > ttl_days:
                    stale += 1
            elif age_days > stale_days:
                stale += 1

        stale_profile_items = 0
        profile_touched = False
        for key in self.PROFILE_KEYS:
            section_meta = self._meta_section(profile, key)
            for _, entry in section_meta.items():
                if not isinstance(entry, dict):
                    continue
                last_seen = self._to_datetime(str(entry.get("last_seen_at", "")))
                if not last_seen:
                    continue
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                age_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)
                if age_days > stale_days:
                    stale_profile_items += 1
                    if update_profile and entry.get("status") != self.PROFILE_STATUS_STALE:
                        entry["status"] = self.PROFILE_STATUS_STALE
                        profile_touched = True

        if update_profile:
            profile["last_verified_at"] = self._utc_now_iso()
            profile_touched = True
            if profile_touched:
                self.write_profile(profile)

        open_conflicts = [
            c
            for c in profile.get("conflicts", [])
            if isinstance(c, dict)
            and str(c.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}
        ]
        belief_quality = self.verify_beliefs()

        report = {
            "events": len(events),
            "profile_items": sum(len(self._to_str_list(profile.get(k))) for k in self.PROFILE_KEYS),
            "open_conflicts": len(open_conflicts),
            "stale_events": stale,
            "stale_profile_items": stale_profile_items,
            "ttl_tracked_events": total_ttl,
            "last_verified_at": profile.get("last_verified_at"),
            "belief_quality": belief_quality["summary"],
        }
        return report

    def verify_beliefs(self) -> dict[str, Any]:
        """Assess belief health based on evidence quality, not just timestamps.

        Delegates to ``ProfileManager.verify_beliefs`` — see LAN-209.
        """
        return self.profile_mgr.verify_beliefs()

    def _select_messages_for_consolidation(
        self,
        session: Session,
        *,
        archive_all: bool,
        memory_window: int,
    ) -> tuple[list[dict[str, Any]], int, int] | None:
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            source_start = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
            return old_messages, keep_count, source_start

        keep_count = memory_window // 2
        if len(session.messages) <= keep_count:
            return None
        if len(session.messages) - session.last_consolidated <= 0:
            return None
        old_messages = session.messages[session.last_consolidated : -keep_count]
        source_start = session.last_consolidated
        if not old_messages:
            return None
        logger.info(
            "Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count
        )
        return old_messages, keep_count, source_start

    @staticmethod
    def _format_conversation_lines(old_messages: list[dict[str, Any]]) -> list[str]:
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(
                f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}"
            )
        return lines

    @staticmethod
    def _build_consolidation_prompt(current_memory: str, lines: list[str]) -> str:
        return f"""Process this conversation and call the save_memory tool with a history_entry summarizing key events, decisions, and topics.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

    _PINNED_START = "<!-- user-pinned -->"
    _PINNED_END = "<!-- end-user-pinned -->"

    @classmethod
    def _extract_pinned_section(cls, text: str) -> str | None:
        """Extract user-pinned content from MEMORY.md, if present."""
        start = text.find(cls._PINNED_START)
        end = text.find(cls._PINNED_END)
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + len(cls._PINNED_END)]

    @classmethod
    def _restore_pinned_section(cls, new_text: str, pinned: str) -> str:
        """Re-insert a pinned section into new MEMORY.md content.

        If the new text already contains a pinned fence, replace it.
        Otherwise insert the pinned block after the first heading.
        """
        existing = cls._extract_pinned_section(new_text)
        if existing:
            return new_text.replace(existing, pinned)
        # Insert after the first heading line (or at the top).
        lines = new_text.split("\n")
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("#"):
                insert_at = i + 1
                break
        lines.insert(insert_at, pinned)
        return "\n".join(lines)

    def _apply_save_memory_tool_result(self, *, args: dict[str, Any], current_memory: str) -> None:
        if entry := args.get("history_entry"):
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)
            self.append_history(entry)
        # memory_update is intentionally ignored (LAN-206): MEMORY.md is now a
        # pure projection rebuilt deterministically via rebuild_memory_snapshot().

    def _finalize_consolidation(
        self, session: Session, *, archive_all: bool, keep_count: int
    ) -> None:
        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        logger.info(
            "Memory consolidation done: {} messages, last_consolidated={}",
            len(session.messages),
            session.last_consolidated,
        )

    # Temporary alias — will be removed in Task 7
    def _sync_events_to_mem0(self, events: list[dict[str, Any]]) -> int:
        return self.ingester._sync_events_to_mem0(events)

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        memory_mode: str | None = None,
        enable_contradiction_check: bool = True,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        t0 = time.monotonic()
        selection = self._select_messages_for_consolidation(
            session,
            archive_all=archive_all,
            memory_window=memory_window,
        )
        if selection is None:
            return True
        old_messages, keep_count, source_start = selection

        lines = self._format_conversation_lines(old_messages)

        current_memory = self.read_long_term()
        prompt = self._build_consolidation_prompt(current_memory, lines)

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": prompts.get("consolidation"),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = self.extractor.parse_tool_args(response.tool_calls[0].arguments)
            if not args:
                logger.warning(
                    "Memory consolidation: unexpected arguments type {}", type(args).__name__
                )
                return False

            self._apply_save_memory_tool_result(args=args, current_memory=current_memory)

            profile = self.read_profile()
            events, profile_updates = await self.extractor.extract_structured_memory(
                provider,
                model,
                profile,
                lines,
                old_messages,
                source_start=source_start,
            )
            events_written = self.ingester.append_events(events)
            await self.ingester._ingest_graph_triples(events)
            # Thread event IDs into profile updates for evidence linking (LAN-197).
            event_ids = [e.get("id", "") for e in events if e.get("id")]
            profile_added, _, profile_touched = self._apply_profile_updates(
                profile,
                profile_updates,
                enable_contradiction_check=enable_contradiction_check,
                source_event_ids=event_ids,
            )
            if events_written > 0 or profile_added > 0 or profile_touched > 0:
                profile["last_verified_at"] = self._utc_now_iso()
                self.write_profile(profile)

            # Track extraction source and per-type distribution

            if profile_added > 0:
                self.auto_resolve_conflicts(max_items=10)

            # MEMORY.md is a pure projection from profile + events (LAN-206).
            self.rebuild_memory_snapshot(write=True)

            # LAN-208: sync structured events to mem0 as the primary indexing
            # path — mem0 is a semantic index, not a raw transcript store.
            if self.mem0.enabled and events:
                self.ingester._sync_events_to_mem0(events)

            # LAN-208: raw conversation turn ingestion — legacy behaviour, gated
            # behind _mem0_raw_turn_ingestion (default True for backward compat).
            if self.mem0.enabled and self._mem0_raw_turn_ingestion:
                for m in old_messages:
                    role = str(m.get("role", "user")).strip().lower() or "user"
                    content = str(m.get("content", "")).strip()
                    if not content:
                        continue
                    memory_type = "episodic"
                    if role == "user":
                        memory_type = (
                            "semantic"
                            if self._contains_any(
                                content,
                                (
                                    "prefer",
                                    "always",
                                    "never",
                                    "must",
                                    "cannot",
                                    "my setup",
                                    "i use",
                                ),
                            )
                            else "episodic"
                        )
                    turn_meta, _ = self.ingester._normalize_memory_metadata(
                        {
                            "topic": "conversation_turn",
                            "memory_type": memory_type,
                            "stability": "medium",
                        },
                        event_type="fact",
                        summary=content,
                        source="chat",
                    )
                    turn_meta.update(
                        {
                            "event_type": "conversation_turn",
                            "role": role,
                            "timestamp": str(m.get("timestamp", "")),
                            "session": session.key,
                        }
                    )
                    clean_content = self.ingester._sanitize_mem0_text(content, allow_archival=False)
                    turn_meta = self.ingester._sanitize_mem0_metadata(turn_meta)
                    if clean_content:
                        self.mem0.add_text(
                            clean_content,
                            metadata=turn_meta,
                        )

            self._finalize_consolidation(
                session,
                archive_all=archive_all,
                keep_count=keep_count,
            )
            bind_trace().debug(
                "Memory consolidate events={} duration_ms={:.0f}",
                events_written,
                (time.monotonic() - t0) * 1000,
            )
            return True
        except Exception:  # crash-barrier: multi-stage consolidation must not crash
            logger.exception("Memory consolidation failed")
            return False
