# Memory Phase 4: Split Oversized Files — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get all memory subsystem files under the 500 LOC hard limit by extracting secondary responsibilities along natural seams identified through exhaustive dependency analysis.

**Architecture:** Each oversized file is split along its responsibility clusters. Extracted code moves to new files in the same subpackage. The original file keeps its public API — extracted methods become imports, not copies. No behavioral changes, no new features. Tests that directly import from split files are updated in the same commit.

**Tech Stack:** Python 3.10+, ruff, mypy, pytest

**Pre-conditions:** Phases 0-2 merged (PRs #99, #101, #104). Worktree at `C:\Users\C95071414\Documents\nanobot-refactor-memory-phase4`.

---

## Scope: 5 Splits + 1 Size Exception

| File | Current LOC | Action | Target LOC |
|------|------------|--------|------------|
| `persistence/profile_io.py` | 707 | Extract belief lifecycle → `belief_lifecycle.py` | ~480 |
| `read/context_assembler.py` | 606 | Extract long-term capping + budget allocation | ~430 |
| `write/extractor.py` | 510 | Extract correction detector + heuristic extractor | ~250 |
| `write/conflicts.py` | 592 | Extract user interaction → `conflict_interaction.py` | ~450 |
| `graph/graph.py` | 557 | Extract traversal → `graph_traversal.py` | ~400 |
| `graph/entity_classifier.py` | 590 | **Size exception** (86% data, 14% logic) | 590 |

## Investigation Summary

Each split was identified through exhaustive method-level dependency analysis:
- Every method's internal and external callers were traced via grep
- Responsibility clusters were identified by call-graph cohesion
- Only clusters with **clean extraction boundaries** (one-way dependencies) are extracted
- Clusters with circular internal dependencies stay in the original file

Full investigation data is available in the exploration agent outputs from this session.

---

## Task 1: Split `profile_io.py` — Extract Belief Lifecycle

**Current:** 707 LOC. ProfileStore handles CRUD + metadata + belief lifecycle + verification + delegation.
**Extract:** Belief add/update/retract methods (~190 LOC) into `persistence/belief_lifecycle.py`.
**Keeps:** CRUD, metadata helpers, verification, delegation, legacy pin/stale helpers.

**Files:**
- Create: `nanobot/memory/persistence/belief_lifecycle.py`
- Modify: `nanobot/memory/persistence/profile_io.py`
- Modify: `nanobot/memory/persistence/__init__.py` (if exports change)
- Test: existing tests (update imports)

### What Moves

These methods move from `ProfileStore` to standalone functions in `belief_lifecycle.py`:

| Method | LOC | Why it moves |
|--------|-----|-------------|
| `_belief_from_meta()` | 16 | Constructs BeliefRecord from meta dict |
| `_find_belief_by_id()` | 13 | Scans profile for belief by ID |
| `get_belief_by_id()` | 14 | Public lookup by stable ID |
| `add_belief()` | 30 | Public API: create belief |
| `_add_belief_to_profile()` | 40 | In-memory belief creation |
| `update_belief()` | 25 | Public API: update belief |
| `_update_belief_in_profile()` | 58 | In-memory belief update |
| `retract_belief()` | 24 | Public API: retract belief |
| `_retract_belief_in_profile()` | 30 | In-memory belief retraction |

**Total extracted:** ~250 LOC (methods + imports/docstring)

### Dependencies the extracted code needs from ProfileStore

The belief methods call these ProfileStore methods:
- `read_profile()`, `write_profile()` — for public wrappers
- `_meta_section()`, `_meta_entry()`, `_touch_meta_entry()` — metadata access
- `_validate_profile_field()` — field validation
- `_norm_text()`, `_to_str_list()`, `_safe_float()`, `_utc_now_iso()` — utilities

**Approach:** The extracted functions receive a `ProfileStore` instance as their first parameter. They call `store.read_profile()`, `store._meta_entry()`, etc. This keeps the metadata infrastructure in ProfileStore (where it belongs) while extracting the belief lifecycle logic.

### External callers that need updating

| Caller | Current call | After extraction |
|--------|-------------|-----------------|
| `ConflictManager._apply_profile_updates()` | `self.profile_mgr._add_belief_to_profile(...)` | Same (ProfileStore delegates) |
| `ConflictManager.resolve_conflict_details()` | `self.profile_mgr._update_belief_in_profile(...)` | Same (ProfileStore delegates) |

**Key insight:** ConflictManager calls belief methods ON the ProfileStore instance. After extraction, ProfileStore keeps thin delegation methods that call the extracted functions. External callers don't change.

### Steps

- [ ] **Step 1:** Create `nanobot/memory/persistence/belief_lifecycle.py` with the 9 methods as module-level functions, each taking `store: ProfileStore` as first param.

- [ ] **Step 2:** In `profile_io.py`, replace the method bodies with delegation calls:
```python
def add_belief(self, field, text, **kw):
    return belief_lifecycle.add_belief(self, field, text, **kw)
```

- [ ] **Step 3:** Run `make lint && make typecheck`

- [ ] **Step 4:** Run `PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`

- [ ] **Step 5:** Verify LOC: `wc -l nanobot/memory/persistence/profile_io.py nanobot/memory/persistence/belief_lifecycle.py`
Expected: profile_io.py ~480, belief_lifecycle.py ~250

- [ ] **Step 6:** Commit
```bash
git commit -m "refactor(memory): extract belief lifecycle from profile_io.py into belief_lifecycle.py"
```

---

## Task 2: Split `context_assembler.py` — Extract Capping + Budget Allocation

**Current:** 606 LOC. ContextAssembler handles orchestration + rendering + capping + budget allocation.
**Extract:** Long-term capping (~83 LOC) into `read/long_term_capping.py`, budget allocation (~74 LOC) into existing `token_budget.py`.
**Keeps:** `build()` orchestration, profile/event rendering, Protocol classes, data access.

**Files:**
- Create: `nanobot/memory/read/long_term_capping.py`
- Modify: `nanobot/memory/read/context_assembler.py`
- Modify: `nanobot/memory/token_budget.py` (add allocation function)
- Test: `tests/test_store_helpers.py` (update imports for capping tests)

### What Moves

| Method | Target | LOC | Why |
|--------|--------|-----|-----|
| `_split_md_sections()` | `long_term_capping.py` | 18 | Pure markdown parsing, only used by cap |
| `_cap_long_term_text()` | `long_term_capping.py` | 65 | Self-contained truncation logic |
| `_allocate_section_budgets()` | `token_budget.py` | 74 | Stateless classmethod, no instance deps |

**Total extracted:** ~157 LOC

### Steps

- [ ] **Step 1:** Create `nanobot/memory/read/long_term_capping.py` with `split_md_sections()` and `cap_long_term_text()` as module-level functions. `cap_long_term_text` takes an `estimate_tokens_fn` callable parameter.

- [ ] **Step 2:** Move `_allocate_section_budgets()` to `nanobot/memory/token_budget.py` as a module-level function `allocate_section_budgets()`.

- [ ] **Step 3:** In `context_assembler.py`, replace method bodies with imports and delegation.

- [ ] **Step 4:** Update `tests/test_store_helpers.py` imports if tests call `_split_md_sections` or `_cap_long_term_text` directly.

- [ ] **Step 5:** Run `make lint && make typecheck && PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`

- [ ] **Step 6:** Verify LOC: `wc -l nanobot/memory/read/context_assembler.py`
Expected: ~430 LOC

- [ ] **Step 7:** Commit
```bash
git commit -m "refactor(memory): extract long-term capping and budget allocation from context_assembler.py"
```

---

## Task 3: Split `extractor.py` — Extract Correction Detector + Heuristic Extractor

**Current:** 510 LOC. MemoryExtractor handles LLM extraction + heuristic fallback + correction detection.
**Extract:** Correction detection (~91 LOC) into `write/correction_detector.py`, heuristic extraction (~170 LOC) into `write/heuristic_extractor.py`.
**Keeps:** LLM extraction orchestration, `parse_tool_args`, `default_profile_updates`.

**Files:**
- Create: `nanobot/memory/write/correction_detector.py`
- Create: `nanobot/memory/write/heuristic_extractor.py`
- Modify: `nanobot/memory/write/extractor.py`
- Modify: Tests that import correction methods

### What Moves

**To `correction_detector.py`:**

| Method | LOC | External callers |
|--------|-----|-----------------|
| `extract_explicit_preference_corrections()` | 40 | CorrectionOrchestrator (profile_correction.py:58) |
| `extract_explicit_fact_corrections()` | 46 | CorrectionOrchestrator (profile_correction.py:59) |
| `_clean_phrase()` | 5 | Used only by above two methods |

**To `heuristic_extractor.py`:**

| Method/Constant | LOC | External callers |
|-----------------|-----|-----------------|
| `_COMMON_WORDS` | 59 | `_extract_entities()` |
| `_TYPE_CONFIDENCE` | 8 | `heuristic_extract_events()` |
| `_TRIPLE_PATTERNS` | 29 | `_extract_triples_heuristic()` |
| `_extract_entities()` | 24 | `heuristic_extract_events()`, GraphAugmenter |
| `_extract_triples_heuristic()` | 56 | `heuristic_extract_events()` |
| `heuristic_extract_events()` | 66 | `extract_structured_memory()` fallback |

**Also:** Remove orphaned `count_user_corrections()` (25 LOC, zero callers found in codebase).

### Steps

- [ ] **Step 1:** Create `nanobot/memory/write/correction_detector.py` with 3 functions.

- [ ] **Step 2:** Create `nanobot/memory/write/heuristic_extractor.py` with functions + constants.

- [ ] **Step 3:** In `extractor.py`, replace method bodies with imports. Keep `extract_structured_memory()` calling `heuristic_extractor.extract_events()` as fallback. Remove dead `count_user_corrections()`.

- [ ] **Step 4:** Update `nanobot/memory/persistence/profile_correction.py` to import correction functions from new module (currently accesses via `self._extractor.extract_explicit_preference_corrections`).

- [ ] **Step 5:** Update `nanobot/memory/read/graph_augmentation.py` which calls `extractor._extract_entities()` — now imports from `heuristic_extractor`.

- [ ] **Step 6:** Update test imports in `tests/test_knowledge_graph.py` and `tests/test_coverage_push_wave6.py`.

- [ ] **Step 7:** Run `make lint && make typecheck && PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`

- [ ] **Step 8:** Verify LOC: `wc -l nanobot/memory/write/extractor.py nanobot/memory/write/correction_detector.py nanobot/memory/write/heuristic_extractor.py`
Expected: extractor.py ~250, correction_detector.py ~120, heuristic_extractor.py ~200

- [ ] **Step 9:** Commit
```bash
git commit -m "refactor(memory): extract correction detector and heuristic extractor from extractor.py

Remove orphaned count_user_corrections() (dead code, zero callers)."
```

---

## Task 4: Split `conflicts.py` — Extract User Interaction

**Current:** 592 LOC. ConflictManager handles detection + batch updates + auto-resolution + user interaction + resolution.
**Extract:** User-facing interaction methods (~130 LOC) into `write/conflict_interaction.py`.
**Keeps:** Detection, batch updates, auto-resolution, resolution core.

**Files:**
- Create: `nanobot/memory/write/conflict_interaction.py`
- Modify: `nanobot/memory/write/conflicts.py`
- Test: existing tests (ConflictManager delegates, no import changes needed)

### What Moves

| Method | LOC | Why |
|--------|-----|-----|
| `_parse_conflict_user_action()` | 18 | Pure text parsing |
| `get_next_user_conflict()` | 17 | UI flow helper |
| `_conflict_relevant_to()` | 12 | Relevance gate |
| `ask_user_for_conflict()` | 52 | User prompt formatting |
| `handle_user_conflict_reply()` | 30 | User reply processing |

**Total:** ~130 LOC

### Dependencies

The extracted functions need:
- `ConflictManager.list_conflicts()` — for `get_next_user_conflict()`
- `ConflictManager.resolve_conflict_details()` — for `handle_user_conflict_reply()`
- `profile_mgr.read_profile()`, `profile_mgr.write_profile()` — for `ask_user_for_conflict()`

**Approach:** Functions receive `ConflictManager` as first parameter and call its methods. ConflictManager keeps thin delegation stubs for backward compatibility.

### Steps

- [ ] **Step 1:** Create `nanobot/memory/write/conflict_interaction.py` with 5 functions.

- [ ] **Step 2:** In `conflicts.py`, replace method bodies with delegation to the new module.

- [ ] **Step 3:** Run `make lint && make typecheck && PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`

- [ ] **Step 4:** Verify LOC: `wc -l nanobot/memory/write/conflicts.py nanobot/memory/write/conflict_interaction.py`
Expected: conflicts.py ~450, conflict_interaction.py ~160

- [ ] **Step 5:** Commit
```bash
git commit -m "refactor(memory): extract user interaction from conflicts.py into conflict_interaction.py"
```

---

## Task 5: Split `graph.py` — Extract Traversal

**Current:** 557 LOC. KnowledgeGraph handles entity/relationship CRUD + traversal + sync helpers.
**Extract:** Complex traversal methods (~163 LOC) into `graph/graph_traversal.py`.
**Keeps:** Entity/relationship CRUD, basic neighbors, search, sync helpers.

**Files:**
- Create: `nanobot/memory/graph/graph_traversal.py`
- Modify: `nanobot/memory/graph/graph.py`
- Test: `tests/test_knowledge_graph.py`, `tests/test_graph_driver_paths.py` (update if needed)

### What Moves

| Method | LOC | Why |
|--------|-----|-----|
| `find_paths()` | 83 | Self-contained BFS path-finding |
| `query_subgraph()` | 30 | Merges neighborhoods (calls get_neighbors) |

**Note:** `get_neighbors()` stays in graph.py — it's used by sync helpers and is the core BFS building block. `find_paths` and `query_subgraph` are higher-level traversal that builds on it.

**Total:** ~113 LOC + imports

### Dependencies

`find_paths()` needs: `_norm()`, `_db.get_entity()`, `_db.get_edges_from()`, `_db.get_edges_to()`, `_get_display_name()`
`query_subgraph()` needs: `get_neighbors()`

**Approach:** Functions receive `KnowledgeGraph` instance as first parameter.

### Steps

- [ ] **Step 1:** Create `nanobot/memory/graph/graph_traversal.py` with `find_paths()` and `query_subgraph()`.

- [ ] **Step 2:** In `graph.py`, replace method bodies with delegation.

- [ ] **Step 3:** Run `make lint && make typecheck && PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`

- [ ] **Step 4:** Verify LOC: `wc -l nanobot/memory/graph/graph.py nanobot/memory/graph/graph_traversal.py`
Expected: graph.py ~430, graph_traversal.py ~140

- [ ] **Step 5:** Commit
```bash
git commit -m "refactor(memory): extract traversal from graph.py into graph_traversal.py"
```

---

## Task 6: Entity Classifier Size Exception + Final Verification

**Files:**
- Modify: `nanobot/memory/graph/entity_classifier.py` (add size-exception comment)

### Entity Classifier Justification

The investigation found:
- **590 LOC total**: 507 LOC data (86%), 83 LOC logic (14%)
- Data: 16 entity type keyword sets, phrase patterns, suffix patterns, role keywords, stopwords
- Logic: `classify_entity_type_scored()` (61 LOC), `classify_entity_type()` (7 LOC), `refine_type_from_predicate()` (15 LOC)
- **Single responsibility**: entity type classification from names
- **No natural seam**: data and logic are tightly coupled (6-signal scoring pipeline reads all data)
- Splitting data into JSON/YAML would add I/O overhead and lose type safety

### Steps

- [ ] **Step 1:** Add size-exception comment to `entity_classifier.py` line 1:
```python
# size-exception: entity type classification — 86% data (16 entity type keyword sets), 14% logic
```

- [ ] **Step 2:** Verify ALL files under 500 LOC (except entity_classifier with exception):
```bash
find nanobot/memory -name "*.py" -exec wc -l {} + | sort -rn | head -15
```

- [ ] **Step 3:** Run `make pre-push`

- [ ] **Step 4:** Dispatch code review subagent for entire Phase 4

- [ ] **Step 5:** Push and create PR

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Test imports break | Medium | Low | All direct imports updated in same commit; grep for old names |
| Delegation stubs add indirection | Low | Low | One extra function call; negligible performance |
| Package file count exceeds 15 | Low | Medium | Check after all splits; write/ goes from 8 to 10 files |
| Circular imports in extracted files | Medium | High | Extracted functions receive parent class as parameter; no import back |

## Package File Count Check

| Package | Current files | After splits | Limit |
|---------|--------------|-------------|-------|
| `persistence/` | 4 | 5 (+belief_lifecycle.py) | 15 |
| `read/` | 6 | 7 (+long_term_capping.py) | 15 |
| `write/` | 8 | 10 (+correction_detector.py, +heuristic_extractor.py, +conflict_interaction.py) | 15 |
| `graph/` | 7 | 8 (+graph_traversal.py) | 15 |

All within limits.
