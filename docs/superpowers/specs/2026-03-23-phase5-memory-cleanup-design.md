# Phase 5: Memory Subsystem Cleanup

**Date:** 2026-03-23
**Topic:** Clean up memory subsystem internal boundaries and reduce confusion
**Status:** Approved
**Part of:** Comprehensive agent refactoring (Phase 5 of 5)
**Depends on:** Phases 1-4 (no direct dependency, but should be done last as it's the most self-contained)

---

## Goal

Improve the internal structure of `nanobot/agent/memory/` (30 files, ~11,500 lines) by:
1. Merging files with unclear boundary distinctions
2. Removing the double-hop re-export facade
3. Moving the eval runner out of the production memory package
4. Updating the outdated `__init__.py` docstring

This is a **cleanup** phase, not a redesign. The memory subsystem's external boundary is healthy — only `MemoryStore` is imported from outside — so we focus on internal clarity.

## Motivation

The memory subsystem has grown organically from ~6 files to 30 files. Most boundaries are clean, but a few areas cause confusion:

1. **`retriever.py` (1,107 lines) vs `retrieval.py` (289 lines)** — naming is nearly identical, and `retrieval.py` is a private implementation detail of `retriever.py` (it exports standalone functions that only `retriever.py` calls)
2. **`ontology.py` (69 lines)** is a pure re-export facade importing from `ontology_types.py`, `ontology_rules.py`, `entity_classifier.py`, `entity_linker.py`. The `__init__.py` imports from `ontology.py` which re-imports from the four files — a double-hop that adds indirection for no consumer benefit
3. **`eval.py` (401 lines)** — `EvalRunner` is a benchmark/observability runner wired into `MemoryStore`. It's a build-time/CI concern mixed into production code
4. **`__init__.py` docstring (lines 1-36)** lists only the original ~6 files and doesn't mention the 20+ modules added since

## Approach

### Change 1: Merge `retrieval.py` into `retriever.py`

`retrieval.py` exports two functions: `_local_retrieve()` and `_topic_fallback_retrieve()`. Both are imported only by `retriever.py:27`. No other file imports from `retrieval.py`.

**Action:** Move the contents of `retrieval.py` into `retriever.py` as private functions. Delete `retrieval.py`.

**Impact on `retriever.py`:** Grows from 1,107 to ~1,396 lines. This is large but acceptable — `MemoryRetriever` is the orchestrator for the entire read path, and the merged functions are implementation details that belong with it. An alternative would be to keep them separate but rename `retrieval.py` to something unambiguous (e.g., `keyword_search.py`).

**Recommendation:** Rename to `keyword_search.py` rather than merge. This preserves the smaller file while eliminating the naming confusion. `retriever.py` imports change from `from .retrieval import ...` to `from .keyword_search import ...`.

### Change 2: Flatten the ontology re-export

`ontology.py` is a 69-line facade that only re-exports:
```python
from .entity_classifier import classify_entity_type, EntityType
from .entity_linker import ...
from .ontology_rules import RELATION_RULES, ...
from .ontology_types import ...
```

And `__init__.py` imports from `ontology.py`.

**Action:** Remove `ontology.py`. Update `__init__.py` to import directly from the source modules (`ontology_types.py`, `ontology_rules.py`, `entity_classifier.py`, `entity_linker.py`). Any internal memory/ files that import from `ontology.py` are updated to import from the source modules directly.

**Verify consumers:** Grep for `from nanobot.agent.memory.ontology import` and `from .ontology import` to find all importers.

### Change 3: Move `eval.py` to a separate location

`EvalRunner` is a benchmark runner with no runtime role — it's called from `cli/commands.py:memory_eval` and from CI scripts. It shouldn't live inside the production memory package.

**Action:** Move `eval.py` to `nanobot/agent/memory/eval.py` → `nanobot/eval/memory_eval.py` (or `tests/eval/memory_eval.py` if the team prefers test-adjacent placement).

**Update:**
- `memory/store.py` — remove `EvalRunner` construction from `MemoryStore.__init__` (it's currently wired at construction time). Instead, `cli/commands.py:memory_eval` constructs `EvalRunner` directly.
- `memory/__init__.py` — remove `EvalRunner` from exports
- `cli/commands.py` — update import path

**Risk:** Low. `EvalRunner` is self-contained — it only depends on `helpers.py` and `persistence.py`.

### Change 4: Update `__init__.py` docstring

The current docstring (lines 1-36) describes an architecture from when the memory package had ~6 files. It doesn't mention `ingester.py`, `retriever.py`, `context_assembler.py`, `conflicts.py`, `consolidation_pipeline.py`, `profile_io.py`, `maintenance.py`, `snapshot.py`, `retrieval_planner.py`, `token_budget.py`, or any of the ontology files.

**Action:** Rewrite the docstring to accurately list all current modules and their roles. Group by concern:
- **Write path:** `extractor.py`, `ingester.py`, `persistence.py`
- **Read path:** `retriever.py`, `keyword_search.py` (renamed), `retrieval_planner.py`, `reranker.py`, `onnx_reranker.py`, `context_assembler.py`, `token_budget.py`
- **Storage:** `mem0_adapter.py`, `persistence.py`
- **Profile:** `profile_io.py`, `profile_correction.py`
- **Knowledge graph:** `graph.py`, `ontology_types.py`, `ontology_rules.py`, `entity_classifier.py`, `entity_linker.py`
- **Lifecycle:** `consolidation_pipeline.py`, `maintenance.py`, `snapshot.py`, `conflicts.py`
- **Infrastructure:** `event.py`, `constants.py`, `helpers.py`, `rollout.py`

---

## What this phase does NOT do

- **No large file splitting** — `retriever.py` (1,107), `ingester.py` (895), `mem0_adapter.py` (874) are large but each has a single clear responsibility. Splitting them would be speculative.
- **No API changes to `MemoryStore`** — the facade remains the sole external interface
- **No changes to the write or read paths** — same behavior, just cleaner file organization
- **No changes to backward-compat aliases** in `__init__.py` (`ProfileManager`, `CrossEncoderReranker`) — these stay until a major version bump

## Constraints

- No behavioral change
- `MemoryStore` remains the only externally imported symbol
- All existing tests pass
- Backward-compat aliases in `__init__.py` are preserved
- The `context_assembler.py` ↔ `snapshot.py` tight coupling (private method sharing at `store.py:247-249`) is noted but NOT addressed — it's a design issue for a future iteration

## Success criteria

- `retrieval.py` is renamed to `keyword_search.py` (clear naming)
- `ontology.py` facade is removed (direct imports)
- `eval.py` is moved out of the production memory package
- `__init__.py` docstring accurately describes all current modules
- `make check` passes
- All existing tests pass
