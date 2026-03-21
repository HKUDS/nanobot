"""Memory store facade — coordinates subsystem modules.

``MemoryStore`` is a thin facade that composes focused subsystem modules:

- ``EventIngester`` — event write path (classify, dedup, merge, append)
- ``MemoryRetriever`` — retrieval read path (mem0, BM25, reranking)
- ``MemoryMaintenance`` — reindex, seed, health checks
- ``MemorySnapshot`` — rebuild and verify MEMORY.md
- ``RolloutConfig`` — feature flag management

Cross-cutting coordination (``consolidate``, ``get_memory_context``) stays
on ``MemoryStore``.  Callers access subsystems directly for specific
operations: ``store.ingester.append_events(...)``.
"""

from __future__ import annotations

import json
import time
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
from .maintenance import MemoryMaintenance
from .mem0_adapter import _Mem0Adapter
from .persistence import MemoryPersistence
from .profile import ProfileManager
from .reranker import CompositeReranker, Reranker
from .retrieval_planner import RetrievalPlanner
from .retriever import MemoryRetriever
from .rollout import RolloutConfig
from .snapshot import MemorySnapshot

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


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
        self.retriever: MemoryRetriever  # set after graph/ingester init
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
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            persistence=self.persistence,
            planner=self._planner,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            read_long_term_fn=lambda: self.persistence.read_text(self.memory_file),
            build_graph_context_lines_fn=lambda *a, **kw: self.retriever._build_graph_context_lines(
                *a, **kw
            ),
        )

        # MemoryMaintenance: reindex, seed, health checks, backend stats.
        self.maintenance = MemoryMaintenance(
            mem0=self.mem0,
            persistence=self.persistence,
            rollout=self.rollout,
        )
        # Wire reindex callback so health check can trigger reindex.
        self.maintenance._reindex_fn = lambda: self.maintenance.reindex_from_structured_memory(
            read_profile_fn=self.profile_mgr.read_profile,
            read_events_fn=self.ingester.read_events,
            ingester=self.ingester,
            profile_keys=self.PROFILE_KEYS,
            vector_points_count_fn=self.maintenance._vector_points_count,
            mem0_get_all_rows_fn=self.maintenance._mem0_get_all_rows,
        )

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

        # MemoryRetriever: owns the full retrieval read path.
        self.retriever = MemoryRetriever(
            mem0=self.mem0,
            graph=self.graph,
            planner=self._planner,
            reranker=self._reranker,
            profile_mgr=self.profile_mgr,
            rollout=self.rollout,
            read_events_fn=self.ingester.read_events,
            extractor=self.extractor,
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
        self.eval_runner = EvalRunner(
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            persistence=self.persistence,
            workspace=self.workspace,
            get_rollout_status_fn=lambda: self._rollout_config.get_status(),
            get_rollout_fn=lambda: self.rollout,
            get_backend_stats_fn=lambda: self.maintenance._backend_stats_for_eval(),
        )

        # MemorySnapshot: rebuild MEMORY.md + verify memory integrity.
        self.snapshot = MemorySnapshot(
            profile_mgr=self.profile_mgr,
            persistence=self.persistence,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            profile_section_lines_fn=lambda profile, **kw: self._assembler._profile_section_lines(
                profile, **kw
            ),
            recent_unresolved_fn=lambda events, **kw: self._assembler._recent_unresolved(
                events, **kw
            ),
            read_long_term_fn=lambda: self.persistence.read_text(self.memory_file),
            write_long_term_fn=lambda content: self.persistence.write_text(
                self.memory_file, content
            ),
            extract_pinned_section_fn=self._extract_pinned_section,
            restore_pinned_section_fn=self._restore_pinned_section,
            verify_beliefs_fn=lambda: self.profile_mgr.verify_beliefs(),
            write_profile_fn=lambda profile: self.profile_mgr.write_profile(profile),
            profile_keys=self.PROFILE_KEYS,
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
    _contains_any = staticmethod(_contains_any)

    # Keep class-level constants as aliases so test code referencing
    # MemoryStore._SECTION_PRIORITY_WEIGHTS / ._SECTION_MIN_TOKENS still works.
    _SECTION_PRIORITY_WEIGHTS = ContextAssembler._SECTION_PRIORITY_WEIGHTS
    _SECTION_MIN_TOKENS = ContextAssembler._SECTION_MIN_TOKENS
    _MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.
    _CORRECTION_MARKERS = ConflictManager._CORRECTION_MARKERS

    # ------------------------------------------------------------------
    # get_memory_context — facade method (lazy assembler init)
    # ------------------------------------------------------------------

    def _ensure_assembler(self) -> ContextAssembler:
        """Return a ``ContextAssembler``, creating it lazily if needed.

        Lazy creation supports test code that constructs ``MemoryStore`` via
        ``__new__`` (bypassing ``__init__``) and then monkeypatches methods
        before calling ``get_memory_context``.
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
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            persistence=persistence,  # type: ignore[arg-type]
            planner=planner,
            read_events_fn=lambda **kw: self.ingester.read_events(**kw),
            read_long_term_fn=lambda: self.persistence.read_text(self.memory_file),
            build_graph_context_lines_fn=lambda *a, **kw: self.retriever._build_graph_context_lines(
                *a, **kw
            ),
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

    # ------------------------------------------------------------------
    # Consolidation pipeline — coordination logic that stays on MemoryStore
    # ------------------------------------------------------------------

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
            self.persistence.append_text(self.history_file, entry.rstrip() + "\n\n")
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

        current_memory = self.persistence.read_text(self.memory_file)
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

            profile = self.profile_mgr.read_profile()
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
            profile_added, _, profile_touched = self.profile_mgr._apply_profile_updates(
                profile,
                profile_updates,
                enable_contradiction_check=enable_contradiction_check,
                source_event_ids=event_ids,
            )
            if events_written > 0 or profile_added > 0 or profile_touched > 0:
                profile["last_verified_at"] = _utc_now_iso()
                self.profile_mgr.write_profile(profile)

            # Track extraction source and per-type distribution

            if profile_added > 0:
                self.conflict_mgr.auto_resolve_conflicts(max_items=10)

            # MEMORY.md is a pure projection from profile + events (LAN-206).
            self.snapshot.rebuild_memory_snapshot(write=True)

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
                            if _contains_any(
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
                    turn_meta = EventIngester._sanitize_mem0_metadata(turn_meta)
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
