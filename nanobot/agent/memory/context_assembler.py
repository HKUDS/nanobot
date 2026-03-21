"""Context assembler — renders memory context for LLM prompt injection.

Extracted from ``MemoryStore`` (LAN-210) to isolate the ~350-line prompt
rendering pipeline into a focused, testable module.  ``ContextAssembler``
is a pure *read-only* consumer: it never mutates memory state, only formats
it into a single Markdown string suitable for inclusion in the system prompt.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from loguru import logger

from .persistence import MemoryPersistence
from .profile import ProfileManager
from .retrieval_planner import RetrievalPlanner

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

    # ------------------------------------------------------------------
    # Class-level constants (moved from MemoryStore)
    # ------------------------------------------------------------------

    PROFILE_KEYS = (
        "preferences",
        "stable_facts",
        "active_projects",
        "relationships",
        "constraints",
    )

    PROFILE_STATUS_STALE = "stale"
    EPISODIC_STATUS_RESOLVED = "resolved"

    # Intent → per-section priority weights.  Higher weight means the
    # section receives a larger share of the total token budget.  Weights
    # are relative — they're normalised to sum to 1.0 during allocation.
    _SECTION_PRIORITY_WEIGHTS: dict[str, dict[str, float]] = {
        "fact_lookup": {
            "long_term": 0.28,
            "profile": 0.23,
            "semantic": 0.20,
            "episodic": 0.05,
            "reflection": 0.00,
            "graph": 0.19,
            "unresolved": 0.05,
        },
        "debug_history": {
            "long_term": 0.15,
            "profile": 0.10,
            "semantic": 0.10,
            "episodic": 0.35,
            "reflection": 0.05,
            "graph": 0.15,
            "unresolved": 0.10,
        },
        "planning": {
            "long_term": 0.15,
            "profile": 0.15,
            "semantic": 0.20,
            "episodic": 0.20,
            "reflection": 0.05,
            "graph": 0.15,
            "unresolved": 0.10,
        },
        "reflection": {
            "long_term": 0.15,
            "profile": 0.10,
            "semantic": 0.15,
            "episodic": 0.10,
            "reflection": 0.25,
            "graph": 0.15,
            "unresolved": 0.10,
        },
        "constraints_lookup": {
            "long_term": 0.19,
            "profile": 0.28,
            "semantic": 0.24,
            "episodic": 0.05,
            "reflection": 0.00,
            "graph": 0.19,
            "unresolved": 0.05,
        },
        "rollout_status": {
            "long_term": 0.25,
            "profile": 0.15,
            "semantic": 0.30,
            "episodic": 0.00,
            "reflection": 0.00,
            "graph": 0.20,
            "unresolved": 0.10,
        },
        "conflict_review": {
            "long_term": 0.15,
            "profile": 0.20,
            "semantic": 0.20,
            "episodic": 0.15,
            "reflection": 0.00,
            "graph": 0.20,
            "unresolved": 0.10,
        },
    }

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
        retrieve_fn: Callable[..., list[dict[str, Any]]],
        persistence: MemoryPersistence,
        planner: RetrievalPlanner,
        *,
        read_events_fn: Callable[..., list[dict[str, Any]]] | None = None,
        read_long_term_fn: Callable[[], str] | None = None,
        build_graph_context_lines_fn: (
            Callable[[str, list[dict[str, Any]], int], list[str]] | None
        ) = None,
        cap_long_term_text_fn: Callable[[str, int, str], str] | None = None,
        profile_section_lines_fn: Callable[[dict[str, Any]], list[str]] | None = None,
        read_profile_fn: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._profile_mgr = profile_mgr
        self._retrieve_fn = retrieve_fn
        self._persistence = persistence
        self._planner = planner
        self._read_events_fn = read_events_fn
        self._read_long_term_fn = read_long_term_fn
        self._build_graph_context_lines_fn = build_graph_context_lines_fn
        self._cap_long_term_text_fn = cap_long_term_text_fn
        self._profile_section_lines_fn = profile_section_lines_fn
        self._read_profile_fn = read_profile_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
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
        intent = RetrievalPlanner.infer_retrieval_intent(query or "")

        long_term = self._read_long_term()
        profile = (
            self._read_profile_fn()
            if self._read_profile_fn is not None
            else self._profile_mgr.read_profile()
        )

        try:
            retrieved = self._retrieve_fn(
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
        if query and self._build_graph_context_lines_fn is not None:
            raw_graph = self._build_graph_context_lines_fn(
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

        alloc = self._allocate_section_budgets(budget, intent, section_sizes)

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

        lines: list[str] = []

        if long_term_text:
            lines.append("## Long-term Memory (project-specific — cite these verbatim)")
            lines.append(long_term_text)

        if fitted_profile_lines:
            lines.append("## Profile Memory")
            lines.append("User-specific facts, preferences, and constraints:")
            lines.extend(fitted_profile_lines)

        if semantic_lines:
            lines.append("## Relevant Semantic Memories")
            lines.append("Retrieved factual knowledge (use these exact terms when answering):")
            lines.extend(semantic_lines)

        if graph_lines:
            lines.append("## Entity Graph")
            lines.append("Verified entity relationships:")
            lines.extend(graph_lines)

        if episodic_lines:
            lines.append("## Relevant Episodic Memories")
            lines.append("Past events and interactions (cite specific details):")
            lines.extend(episodic_lines)

        if include_reflection and reflection_lines:
            lines.append("## Relevant Reflection Memories")
            lines.extend(reflection_lines)

        if unresolved_lines:
            lines.append("## Recent Unresolved Tasks/Decisions")
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
        if self._read_long_term_fn is not None:
            return self._read_long_term_fn()
        return self._persistence.read_text(self._persistence.memory_file)

    def _read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        if self._read_events_fn is not None:
            return self._read_events_fn(limit=limit)
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
        for key in self.PROFILE_KEYS:
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
                if status == self.PROFILE_STATUS_STALE and not pinned:
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
            if status == self.EPISODIC_STATUS_RESOLVED:
                continue
            summary = str(event.get("summary", "")).strip()
            if not summary or self._is_resolved_task_or_decision(summary):
                continue
            unresolved.append(event)
            if len(unresolved) >= max_items:
                break
        unresolved.reverse()
        return unresolved

    @staticmethod
    def _memory_item_line(item: dict[str, Any]) -> str:
        timestamp = str(item.get("timestamp", ""))[:16]
        event_type = item.get("type", "fact")
        summary = item.get("summary", "")
        reason = item.get("retrieval_reason", {})
        return (
            f"- [{timestamp}] ({event_type}) {summary} "
            f"[sem={reason.get('semantic', 0):.2f}, "
            f"rec={reason.get('recency', 0):.2f}, "
            f"src={reason.get('provider', 'mem0')}]"
        )

    # ------------------------------------------------------------------
    # MEMORY.md capping (Step 5)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_md_sections(text: str) -> list[tuple[str, str]]:
        """Split markdown text into (heading, body) pairs.

        Sections are delimited by ``## `` headings.  Text before the first
        heading is returned with heading ``""``.
        """
        parts = re.split(r"(?m)^(## .+)$", text)
        sections: list[tuple[str, str]] = []
        if parts and not parts[0].startswith("## "):
            preamble = parts.pop(0).strip()
            if preamble:
                sections.append(("", preamble))
        while parts:
            heading = parts.pop(0).strip()
            body = parts.pop(0).strip() if parts else ""
            sections.append((heading, body))
        return sections

    def _cap_long_term_text(
        self,
        long_term_text: str,
        token_cap: int,
        query: str,
    ) -> str:
        """Return *long_term_text* capped to *token_cap* tokens.

        When the full text exceeds the cap, sections are ranked by a simple
        keyword-overlap score against *query* and the top sections that fit
        within the budget are selected (most relevant first).
        """
        if token_cap <= 0 or not long_term_text:
            return long_term_text

        if self._estimate_tokens(long_term_text) <= token_cap:
            return long_term_text

        sections = self._split_md_sections(long_term_text)
        if not sections:
            # No headings — hard-truncate
            chars = token_cap * 4
            return long_term_text[:chars].rsplit("\n", 1)[0] + "\n(long-term memory truncated)"

        # Score each section by keyword overlap with the query
        query_words = set(query.lower().split()) if query else set()

        def _score(heading: str, body: str) -> float:
            text_words = set((heading + " " + body).lower().split())
            overlap = len(query_words & text_words)
            # Boost: shorter sections cost less budget and are proportionally more valuable
            brevity = 1.0 / max(1, self._estimate_tokens(body) / 100)
            return overlap + brevity * 0.5

        scored = sorted(
            sections,
            key=lambda s: _score(s[0], s[1]),
            reverse=True,
        )

        selected: list[tuple[str, str]] = []
        used = 0
        for heading, body in scored:
            section_text = f"{heading}\n{body}" if heading else body
            section_tokens = self._estimate_tokens(section_text)
            if used + section_tokens > token_cap and selected:
                break
            selected.append((heading, body))
            used += section_tokens

        # Preserve original ordering
        original_order = {id(s): i for i, s in enumerate(sections)}
        selected.sort(key=lambda s: original_order.get(id(s), 0))

        out_parts = []
        for heading, body in selected:
            if heading:
                out_parts.append(f"{heading}\n{body}")
            else:
                out_parts.append(body)

        result = "\n\n".join(out_parts)
        if len(selected) < len(sections):
            result += "\n(some long-term memory sections omitted to fit context budget)"
        return result

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

    @classmethod
    def _allocate_section_budgets(
        cls,
        total_budget: int,
        intent: str,
        section_sizes: dict[str, int],
    ) -> dict[str, int]:
        """Distribute *total_budget* tokens across named sections.

        Uses a two-pass proportional allocation:

        1. **Priority pass** — each section gets a share proportional to its
           intent-specific weight, capped at its actual content size.
        2. **Redistribution pass** — tokens freed by sections that are
           smaller than their share are redistributed to sections that need
           more space, again proportionally by weight.

        Parameters
        ----------
        total_budget:
            Total token budget for the combined memory context.
        intent:
            Query intent string (drives prioritisation weights).
        section_sizes:
            Mapping of section name -> estimated token count of the **full**
            (untruncated) content for that section.  Sections missing from
            the map or with size 0 receive no allocation.

        Returns
        -------
        dict mapping section name -> allocated token budget.
        """
        weights = cls._SECTION_PRIORITY_WEIGHTS.get(
            intent,
            cls._SECTION_PRIORITY_WEIGHTS["fact_lookup"],
        )

        # Filter to sections that actually have content *and* non-zero weight.
        active: dict[str, float] = {}
        for name, weight in weights.items():
            size = section_sizes.get(name, 0)
            if size > 0 and weight > 0:
                active[name] = weight

        if not active:
            return {name: 0 for name in weights}

        total_weight = sum(active.values())
        allocations: dict[str, int] = {name: 0 for name in weights}

        # Pass 1: proportional allocation capped at actual size.
        surplus = 0
        uncapped: dict[str, float] = {}
        for name, weight in active.items():
            share = int(total_budget * (weight / total_weight))
            actual_size = section_sizes.get(name, 0)
            if share >= actual_size:
                # Section fits entirely — cap and reclaim the surplus.
                allocations[name] = actual_size
                surplus += share - actual_size
            else:
                # Section needs more than its share.
                allocations[name] = max(share, cls._SECTION_MIN_TOKENS)
                uncapped[name] = weight

        # Pass 2: redistribute surplus to sections that couldn't fit.
        if surplus > 0 and uncapped:
            uncapped_total = sum(uncapped.values())
            for name, weight in uncapped.items():
                extra = int(surplus * (weight / uncapped_total))
                actual_size = section_sizes.get(name, 0)
                allocations[name] = min(allocations[name] + extra, actual_size)

        return allocations

    # ------------------------------------------------------------------
    # Shared utility statics (duplicated from MemoryStore to avoid
    # coupling — these are trivial one-liners)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_resolved_task_or_decision(summary: str) -> bool:
        text = summary.lower()
        resolved_markers = (
            "done",
            "completed",
            "resolved",
            "closed",
            "finished",
            "cancelled",
            "canceled",
        )
        return any(marker in text for marker in resolved_markers)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        value = str(text or "")
        if not value:
            return 0
        return max(1, len(value) // 4)

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _norm_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())
