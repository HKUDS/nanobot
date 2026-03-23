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

`retrieval.py` exports five callable symbols: `_local_retrieve()`, `_topic_fallback_retrieve()`, `_bm25_score()`, `_build_bm25_index()`, `_keyword_score()`.

**Production consumer:** `retriever.py:27` imports from `retrieval.py`.

**Test consumer:** `tests/test_memory_helper_wave5.py:13-18` imports all five symbols directly from `nanobot.agent.memory.retrieval`.

**Action:** Rename `retrieval.py` to `keyword_search.py`. This preserves the smaller file while eliminating the naming confusion with `retriever.py`.

**Required updates:**
- `retriever.py` — change `from .retrieval import ...` to `from .keyword_search import ...`
- `tests/test_memory_helper_wave5.py:13-18` — change import path from `nanobot.agent.memory.retrieval` to `nanobot.agent.memory.keyword_search`

### Change 2: Flatten the ontology re-export

`ontology.py` is a 69-line facade that only re-exports:
```python
from .entity_classifier import classify_entity_type, EntityType
from .entity_linker import ...
from .ontology_rules import RELATION_RULES, ...
from .ontology_types import ...
```

**Production consumers of `ontology.py`:**
- `memory/__init__.py` — imports from `ontology.py`
- `memory/graph.py:25` — `from .ontology import (...)`
- `memory/ingester.py:849` — `from .ontology import Triple`
- `memory/retriever.py:1085` — `from .ontology import classify_entity_type`

**Test consumers (import via `nanobot.agent.memory.ontology`):**
- `tests/test_graph_driver_paths.py` (lines 12, 42, 114)
- `tests/test_knowledge_graph.py:10`
- `tests/test_ontology.py:5`

**Action:** Remove `ontology.py` as a re-export facade. Update all 7 importers:

- `__init__.py` — import directly from `ontology_types.py`, `ontology_rules.py`, `entity_classifier.py`, `entity_linker.py`
- `graph.py`, `ingester.py`, `retriever.py` — change `from .ontology import ...` to import from the specific source module
- 3 test files — change `from nanobot.agent.memory.ontology import ...` to import from the specific source module (e.g., `from nanobot.agent.memory.entity_classifier import classify_entity_type`)

### Change 3: Move `eval.py` to a separate location

`EvalRunner` is a benchmark runner with no runtime role — it's called from `cli/commands.py:memory_eval` and from CI scripts. It shouldn't live inside the production memory package.

**Action:** Move `eval.py` to `nanobot/eval/memory_eval.py`.

**Update:**
- `memory/__init__.py` — remove `EvalRunner` from exports
- `cli/memory.py` (NOT `cli/commands.py` — the `memory_eval` command lives at `cli/memory.py:301`) — update import path. The CLI currently accesses `store.eval_runner.evaluate_retrieval_cases(...)` at lines 403, 407, 408, 460
- `memory/store.py` — keep the `eval_runner` attribute on `MemoryStore` but import `EvalRunner` from the new location. The construction wiring in `store.py.__init__` (lines 234-240) passes six callables (`retrieve_fn`, `get_rollout_status_fn`, `get_rollout_fn`, `get_backend_stats_fn`, plus `MemoryPersistence` and `Path`) — this wiring stays in `store.py` since it requires access to store internals

**Risk:** Low for the file move itself. Note that while `eval.py`'s static imports are limited (`helpers.py`, `persistence.py`), its construction requires six callables wired from `MemoryStore` internals, so `store.py` retains a dependency on the new module location.

### Change 4: Update `__init__.py` docstring

The current docstring (lines 1-36) describes an architecture from when the memory package had ~6 files. It doesn't mention `ingester.py`, `retriever.py`, `context_assembler.py`, `conflicts.py`, `consolidation_pipeline.py`, `profile_io.py`, `maintenance.py`, `snapshot.py`, `retrieval_planner.py`, `token_budget.py`, or any of the ontology files.

**Action:** Rewrite the docstring to accurately list all current modules and their roles. Group by concern:
- **Write path:** `extractor.py`, `ingester.py`, `persistence.py`
- **Read path:** `retriever.py`, `keyword_search.py` (renamed from `retrieval.py` in Change 1), `retrieval_planner.py`, `reranker.py`, `onnx_reranker.py`, `context_assembler.py`, `token_budget.py`
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

- `retrieval.py` is renamed to `keyword_search.py` (clear naming); `tests/test_memory_helper_wave5.py` updated
- `ontology.py` facade is removed; 3 production files and 3 test files updated to direct imports
- `eval.py` is moved out of the production memory package
- `__init__.py` docstring accurately describes all current modules
- `make check` passes
- All existing tests pass
