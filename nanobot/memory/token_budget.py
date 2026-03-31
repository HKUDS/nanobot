"""TokenBudgetAllocator: pure proportional token budget allocation.

Extracted from ContextAssembler._allocate_section_budgets.
No I/O, no subsystem dependencies — pure logic.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEFAULT_SECTION_WEIGHTS",
    "SectionBudget",
    "TokenBudgetAllocator",
    "allocate_section_budgets",
]

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


# ---------------------------------------------------------------------------
# Standalone budget allocation (extracted from ContextAssembler)
# ---------------------------------------------------------------------------

_SECTION_MIN_TOKENS = 40


def allocate_section_budgets(
    total_budget: int,
    intent: str,
    section_sizes: dict[str, int],
    min_tokens: int = _SECTION_MIN_TOKENS,
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
    min_tokens:
        Minimum token allocation per section that needs more than its
        proportional share.

    Returns
    -------
    dict mapping section name -> allocated token budget.
    """
    weights = DEFAULT_SECTION_WEIGHTS.get(
        intent,
        DEFAULT_SECTION_WEIGHTS["fact_lookup"],
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
            allocations[name] = max(share, min_tokens)
            uncapped[name] = weight

    # Pass 2: redistribute surplus to sections that couldn't fit.
    if surplus > 0 and uncapped:
        uncapped_total = sum(uncapped.values())
        for name, weight in uncapped.items():
            extra = int(surplus * (weight / uncapped_total))
            actual_size = section_sizes.get(name, 0)
            allocations[name] = min(allocations[name] + extra, actual_size)

    return allocations
