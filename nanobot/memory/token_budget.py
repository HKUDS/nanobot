"""TokenBudgetAllocator: pure proportional token budget allocation.

Extracted from ContextAssembler._allocate_section_budgets.
No I/O, no subsystem dependencies — pure logic.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_SECTION_WEIGHTS", "SectionBudget", "TokenBudgetAllocator"]

# Default weights mirror _SECTION_PRIORITY_WEIGHTS from context_assembler.py.
# Keys are intent strings from RetrievalPlanner.infer_retrieval_intent().
DEFAULT_SECTION_WEIGHTS: dict[str, dict[str, float]] = {
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

_SECTION_NAMES = (
    "long_term",
    "profile",
    "semantic",
    "episodic",
    "reflection",
    "graph",
    "unresolved",
)


@dataclass(frozen=True, slots=True)
class SectionBudget:
    """Per-section token allocations for a single retrieval call."""

    long_term: int
    profile: int
    semantic: int
    episodic: int
    reflection: int
    graph: int
    unresolved: int


class TokenBudgetAllocator:
    """Allocates a total token budget proportionally across memory sections.

    Weights are normalised to sum to 1.0 at allocation time. Unknown intents
    fall back to 'fact_lookup'. All allocations are clamped to >= 0.
    """

    def __init__(self, weights: dict[str, dict[str, float]]) -> None:
        self._weights = weights

    def allocate(self, total_tokens: int, intent: str) -> SectionBudget:
        """Return a SectionBudget distributing total_tokens by intent weights."""
        weight_map = self._weights.get(intent, self._weights.get("fact_lookup", {}))
        total_weight = sum(w for w in weight_map.values() if w > 0)
        if total_weight == 0:
            return SectionBudget(**{s: 0 for s in _SECTION_NAMES})  # type: ignore[arg-type]
        allocations: dict[str, int] = {}
        for section in _SECTION_NAMES:
            w = weight_map.get(section, 0.0)
            allocations[section] = max(0, int(total_tokens * w / total_weight)) if w > 0 else 0
        return SectionBudget(**allocations)  # type: ignore[arg-type]
