"""Context assembler — renders memory context for LLM prompt injection.

Extracted from ``MemoryStore`` (LAN-210) to isolate the ~350-line prompt
rendering pipeline into a focused, testable module.  ``ContextAssembler``
is a pure *read-only* consumer: it never mutates memory state, only formats
it into a single Markdown string suitable for inclusion in the system prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol

from loguru import logger

from .._text import _estimate_tokens, _norm_text, _safe_float, _to_str_list
from ..constants import EPISODIC_STATUS_RESOLVED, PROFILE_KEYS, PROFILE_STATUS_STALE
from ..event import is_resolved_task_or_decision
from ..persistence.profile_io import ProfileStore as ProfileManager
from ..token_budget import TokenBudgetAllocator, allocate_section_budgets
from .long_term_capping import cap_long_term_text, split_md_sections
from .retrieval_planner import RetrievalPlanner
from .retrieval_types import RetrievedMemory

if TYPE_CHECKING:
    from ..db.connection import MemoryDatabase


class _Retriever(Protocol):
    """Structural type for the retrieval callable."""

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> list[RetrievedMemory]:
        """Retrieve memory items matching *query*."""


class _EventReader(Protocol):
    """Structural type for the event read callable."""

    def read_events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Read events from storage."""


class _GraphAugmenter(Protocol):
    """Structural type for the graph context builder."""

    def build_graph_context_lines(
        self,
        query: str,
        retrieved: list[Any],
        budget: int,
    ) -> list[str]:
        """Build graph context lines for prompt injection."""


# Intents that benefit from scanning recent unresolved events.
# For all other intents (fact_lookup, chitchat, …) the scan is skipped.
_UNRESOLVED_INTENTS: frozenset[str] = frozenset(
    {"planning", "debug", "conflict", "reflection", "task"}
)


class ContextAssembler:
    """Assembles a Markdown memory-context block for LLM prompts.

    Delegates data access through injected callables / collaborators so that
    it never depends on ``MemoryStore`` directly.
    """

    # Minimum token allocation per section — ensures every section gets at
    # least this much budget regardless of priority weight, as long as the
    # section has content.  A section with zero weight or no content gets 0.
    _SECTION_MIN_TOKENS = 40

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        profile_mgr: ProfileManager,
        retriever: _Retriever,
        planner: RetrievalPlanner,
        *,
        event_reader: _EventReader | None = None,
        graph_augmenter: _GraphAugmenter | None = None,
        cap_long_term_text_fn: Callable[[str, int, str], str] | None = None,
        profile_section_lines_fn: Callable[[dict[str, Any]], list[str]] | None = None,
        read_profile_fn: Callable[[], dict[str, Any]] | None = None,
        budget_allocator: TokenBudgetAllocator | None = None,
        db: MemoryDatabase,
        embedder_available: bool = True,
    ) -> None:
        self._profile_mgr = profile_mgr
        self._retriever = retriever
        self._planner = planner
        self._event_reader = event_reader
        self._graph_augmenter = graph_augmenter
        self._cap_long_term_text_fn = cap_long_term_text_fn
        self._profile_section_lines_fn = profile_section_lines_fn
        self._read_profile_fn = read_profile_fn
        self._budget = budget_allocator
        self._db = db
        self._embedder_available = embedder_available

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(
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
        """Assemble a Markdown memory-context string.

        Parameters match ``MemoryStore.get_memory_context`` exactly.
        """
        if not self._embedder_available:
            return (
                "[Memory unavailable: no embedding provider configured. "
                "Memory retrieval is disabled for this session.]"
            )

        intent = RetrievalPlanner.infer_retrieval_intent(query or "")

        long_term = self._read_long_term()
        profile = (
            self._read_profile_fn()
            if self._read_profile_fn is not None
            else self._profile_mgr.read_profile()
        )

        try:
            retrieved = await self._retriever.retrieve(
                query or "",
                top_k=retrieval_k,
                recency_half_life_days=recency_half_life_days,
                embedding_provider=embedding_provider,
            )
        except Exception:  # crash-barrier: multi-subsystem retrieval pipeline
            logger.warning("Memory retrieval failed; continuing with local data only")
            retrieved = []

        budget = max(token_budget, 200)

        # Determine which sections to include based on intent.
        include_episodic = True
        include_reflection = intent == "reflection"

        # ── Phase 1: build raw (untruncated) content for every section ──

        long_term_text = long_term.strip() if long_term else ""

        profile_lines = (
            self._profile_section_lines_fn(profile)
            if self._profile_section_lines_fn is not None
            else self._profile_section_lines(profile)
        )
        profile_text = "\n".join(profile_lines).strip() if profile_lines else ""

        semantic_items = [
            item for item in retrieved if RetrievalPlanner.memory_type_for_item(item) == "semantic"
        ]
        episodic_items = [
            item for item in retrieved if RetrievalPlanner.memory_type_for_item(item) == "episodic"
        ]
        reflection_items = [
            item
            for item in retrieved
            if RetrievalPlanner.memory_type_for_item(item) == "reflection"
        ]

        raw_semantic = [self._memory_item_line(item) for item in semantic_items]
        raw_episodic = [self._memory_item_line(item) for item in episodic_items]
        raw_reflection = [self._memory_item_line(item) for item in reflection_items]

        raw_graph: list[str] = []
        if query and self._graph_augmenter is not None:
            raw_graph = self._graph_augmenter.build_graph_context_lines(
                query,
                retrieved,
                budget,
            )

        unresolved: list[dict[str, Any]] = (
            self._recent_unresolved(self._read_events(limit=60), max_items=6)
            if intent in _UNRESOLVED_INTENTS
            else []
        )
        raw_unresolved: list[str] = []
        if include_episodic and unresolved:
            for item in unresolved:
                ts = str(item.get("timestamp", ""))[:16]
                raw_unresolved.append(
                    f"- [{ts}] ({item.get('type', 'task')}) {item.get('summary', '')}"
                )

        # ── Phase 2: measure raw sizes and allocate budget ──

        raw_long_term_tokens = self._estimate_tokens(long_term_text)
        capped_long_term_tokens = (
            min(raw_long_term_tokens, memory_md_token_cap)
            if memory_md_token_cap > 0
            else raw_long_term_tokens
        )

        section_sizes: dict[str, int] = {
            "long_term": capped_long_term_tokens,
            "profile": self._estimate_tokens(profile_text),
            "semantic": self._estimate_tokens("\n".join(raw_semantic)),
            "episodic": (self._estimate_tokens("\n".join(raw_episodic)) if include_episodic else 0),
            "reflection": (
                self._estimate_tokens("\n".join(raw_reflection)) if include_reflection else 0
            ),
            "graph": self._estimate_tokens("\n".join(raw_graph)),
            "unresolved": self._estimate_tokens("\n".join(raw_unresolved)),
        }

        if self._budget is not None:
            _alloc = self._budget.allocate(budget, intent)
            section_budgets = {
                "long_term": _alloc.long_term,
                "profile": _alloc.profile,
                "semantic": _alloc.semantic,
                "episodic": _alloc.episodic,
                "reflection": _alloc.reflection,
                "graph": _alloc.graph,
                "unresolved": _alloc.unresolved,
            }
        else:
            section_budgets = self._allocate_section_budgets(budget, intent, section_sizes)
        alloc = section_budgets

        # ── Phase 3: fit each section to its allocated budget ──

        if long_term_text and alloc["long_term"] > 0:
            _cap_fn = self._cap_long_term_text_fn or self._cap_long_term_text
            long_term_text = _cap_fn(long_term_text, alloc["long_term"], query or "")

        semantic_lines = self._fit_lines_to_token_cap(
            raw_semantic,
            token_cap=alloc["semantic"],
        )
        episodic_lines = self._fit_lines_to_token_cap(
            raw_episodic,
            token_cap=alloc["episodic"],
        )
        reflection_lines = self._fit_lines_to_token_cap(
            raw_reflection,
            token_cap=alloc["reflection"],
        )
        graph_lines = self._fit_lines_to_token_cap(
            raw_graph,
            token_cap=alloc["graph"],
        )
        unresolved_lines = self._fit_lines_to_token_cap(
            raw_unresolved,
            token_cap=alloc["unresolved"],
        )
        fitted_profile_lines = self._fit_lines_to_token_cap(
            profile_lines,
            token_cap=alloc["profile"],
        )

        # ── Phase 4: assemble in logical presentation order ──
        #
        # Sub-header pattern: (origin — action)
        #   origin  = provenance hint (helps larger models with source attribution)
        #   action  = behavioral directive (helps all models, especially Haiku)
        # See docs/adr/ADR-012-memory-context-header-pattern.md for rationale.

        lines: list[str] = []

        if long_term_text:
            lines.append(
                "## Long-term Memory"
                " (from previous sessions, project-specific — verify before citing)"
            )
            lines.append(long_term_text)

        if fitted_profile_lines:
            lines.append("## Profile Memory (from previous sessions — verify before citing)")
            lines.extend(fitted_profile_lines)

        if semantic_lines:
            lines.append("## Relevant Semantic Memories")
            lines.append(
                "Retrieved factual knowledge"
                " (from previous sessions — verify with tools before citing):"
            )
            lines.extend(semantic_lines)

        if graph_lines:
            lines.append("## Entity Graph (derived relationships — verify before citing)")
            lines.extend(graph_lines)

        if episodic_lines:
            lines.append("## Relevant Episodic Memories")
            lines.append(
                "Past events and interactions (from previous sessions — verify with tools):"
            )
            lines.extend(episodic_lines)

        if include_reflection and reflection_lines:
            lines.append(
                "## Relevant Reflection Memories (from previous sessions — check if still relevant)"
            )
            lines.extend(reflection_lines)

        if unresolved_lines:
            lines.append(
                "## Recent Unresolved Tasks/Decisions"
                " (from previous sessions — check if still open)"
            )
            lines.extend(unresolved_lines)

        text = "\n".join(lines).strip()

        # Final safety net — should rarely trigger now that every section
        # is individually budget-capped, but guards against heading overhead.
        max_chars = budget * 4
        if len(text) > max_chars:
            text = (
                text[:max_chars].rsplit("\n", 1)[0]
                + "\n- ... (memory context truncated to token budget)"
            )

        return text

    # ------------------------------------------------------------------
    # Internal helpers — data access delegates
    # ------------------------------------------------------------------

    def _read_long_term(self) -> str:
        return self._db.read_snapshot("current")

    def _read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        if self._event_reader is not None:
            return self._event_reader.read_events(limit=limit)
        return []

    # ------------------------------------------------------------------
    # Internal helpers — rendering
    # ------------------------------------------------------------------

    def _profile_section_lines(
        self, profile: dict[str, Any], max_items_per_section: int = 6
    ) -> list[str]:
        lines: list[str] = []
        title_map = {
            "preferences": "Preferences",
            "stable_facts": "Stable Facts",
            "active_projects": "Active Projects",
            "relationships": "Relationships",
            "constraints": "Constraints",
        }
        for key in PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            if not values:
                continue
            section_meta = self._profile_mgr._meta_section(profile, key)
            scored_values: list[tuple[str, float, int]] = []
            for value in values:
                meta = (
                    section_meta.get(self._norm_text(value), {})
                    if isinstance(section_meta, dict)
                    else {}
                )
                status = meta.get("status") if isinstance(meta, dict) else None
                pinned = bool(meta.get("pinned")) if isinstance(meta, dict) else False
                if status == PROFILE_STATUS_STALE and not pinned:
                    continue
                conf = self._safe_float(
                    meta.get("confidence") if isinstance(meta, dict) else None, 0.65
                )
                pin_rank = 1 if pinned else 0
                scored_values.append((value, conf, pin_rank))
            scored_values.sort(key=lambda item: (item[2], item[1]), reverse=True)
            if not scored_values:
                continue
            lines.append(f"### {title_map[key]}")
            for item, confidence, pin_rank in scored_values[:max_items_per_section]:
                pin_suffix = " \U0001f4cc" if pin_rank else ""
                lines.append(f"- {item} (conf={confidence:.2f}){pin_suffix}")
            lines.append("")
        return lines

    def _recent_unresolved(
        self, events: list[dict[str, Any]], max_items: int = 8
    ) -> list[dict[str, Any]]:
        unresolved: list[dict[str, Any]] = []
        for event in reversed(events):
            event_type = str(event.get("type", ""))
            if event_type not in {"task", "decision"}:
                continue
            status = str(event.get("status", "")).strip().lower()
            if status == EPISODIC_STATUS_RESOLVED:
                continue
            summary = str(event.get("summary", "")).strip()
            if not summary or is_resolved_task_or_decision(summary):
                continue
            unresolved.append(event)
            if len(unresolved) >= max_items:
                break
        unresolved.reverse()
        return unresolved

    @staticmethod
    def _memory_item_line(item: RetrievedMemory) -> str:
        return (
            f"- [{item.timestamp[:16]}] ({item.type}) {item.summary} "
            f"[sem={item.scores.semantic:.2f}, "
            f"rec={item.scores.recency:.2f}, "
            f"src={item.scores.provider}]"
        )

    # ------------------------------------------------------------------
    # Memory snapshot capping (Step 5)
    # ------------------------------------------------------------------

    # Delegation stubs — logic extracted to long_term_capping.py
    _split_md_sections = staticmethod(split_md_sections)

    def _cap_long_term_text(
        self,
        long_term_text: str,
        token_cap: int,
        query: str,
    ) -> str:
        """Delegate to :func:`long_term_capping.cap_long_term_text`."""
        return cap_long_term_text(long_term_text, token_cap, query, self._estimate_tokens)

    def _fit_lines_to_token_cap(self, lines: list[str], *, token_cap: int) -> list[str]:
        if token_cap <= 0 or not lines:
            return []
        out: list[str] = []
        used = 0
        for line in lines:
            line_tokens = self._estimate_tokens(line)
            if out and used + line_tokens > token_cap:
                out.append("- ... (section truncated to token budget)")
                break
            out.append(line)
            used += line_tokens
        return out

    # ------------------------------------------------------------------
    # Budget-aware context section allocation
    # ------------------------------------------------------------------

    # Delegation stub — logic extracted to token_budget.allocate_section_budgets
    @classmethod
    def _allocate_section_budgets(
        cls,
        total_budget: int,
        intent: str,
        section_sizes: dict[str, int],
    ) -> dict[str, int]:
        """Delegate to :func:`token_budget.allocate_section_budgets`."""
        return allocate_section_budgets(
            total_budget, intent, section_sizes, min_tokens=cls._SECTION_MIN_TOKENS
        )

    # Delegate to canonical function in event.py for backward compat.
    _is_resolved_task_or_decision = staticmethod(is_resolved_task_or_decision)

    # -- Shared helpers imported from ._text ----------------------------------
    _estimate_tokens = staticmethod(_estimate_tokens)
    _to_str_list = staticmethod(_to_str_list)
    _safe_float = staticmethod(_safe_float)
    _norm_text = staticmethod(_norm_text)
