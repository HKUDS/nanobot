# CLAUDE.md Compliance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the existing codebase into compliance with the new CLAUDE.md growth limits (≤12 `__init__.py` exports, ≤500 LOC per file, size-exception comments where justified).

**Architecture:** Three phases — (1) quick wins that don't change behavior, (2) `__init__.py` export reduction, (3) file splits for oversized modules. Each task is one PR. No logic changes — pure structural moves + import rewrites.

**Tech Stack:** Python, ruff, mypy, pytest

**Constraints from CLAUDE.md:**
- `make check` must pass after every PR
- One PR, one change
- No backward-compatibility shims
- Preserve `__all__` exports without an ADR (but reducing exports IS the goal here, so each reduction gets a brief justification in the PR description)

---

## Phase 1: Size-Exception Comments (1 PR)

Quick win. Tag files that are legitimately large with `# size-exception:` comments.
No code changes, no splits — just documenting accepted exceptions.

**Verdict categories from the file-size audit:**
- **SIZE-EXCEPTION (3):** `turn_orchestrator.py`, `config/schema.py`, `loop.py` — core
  architectural pieces whose complexity is inherent, not accidental. Clear exceptions.
- **BORDERLINE (2):** `cli/memory.py`, `memory/graph/graph.py` — defensible either way.
  Marking as exceptions now because splitting adds more indirection than clarity. If either
  grows further, revisit as a split candidate.

### Task 1: Add size-exception comments to justified files

**Files:**
- Modify: `nanobot/agent/turn_orchestrator.py:1` (add comment after `from __future__`)
- Modify: `nanobot/config/schema.py:1` (add comment after `from __future__`)
- Modify: `nanobot/agent/loop.py:1` (add comment after `from __future__`)
- Modify: `nanobot/cli/memory.py:1` (add comment after `from __future__`)
- Modify: `nanobot/memory/graph/graph.py:1` (add comment after `from __future__`)

- [ ] **Step 1: Add size-exception comment to turn_orchestrator.py**

Add after the `from __future__ import annotations` line:
```python
# size-exception: core PAOR state machine — splitting would fragment the agent's central control flow
```

- [ ] **Step 2: Add size-exception comment to config/schema.py**

Add after the `from __future__ import annotations` line:
```python
# size-exception: data definitions — Pydantic config models, no domain logic
```

- [ ] **Step 3: Add size-exception comment to loop.py**

Add after the `from __future__ import annotations` line:
```python
# size-exception: main message loop — control flow must be readable in one place
```

- [ ] **Step 4: Add size-exception comment to cli/memory.py**

Add after the `from __future__ import annotations` line:
```python
# size-exception: CLI command group — each subcommand is thin, splitting adds indirection without benefit
```

- [ ] **Step 5: Add size-exception comment to memory/graph/graph.py**

Add after the `from __future__ import annotations` line:
```python
# size-exception: knowledge graph operations — entity and relationship ops share the SQLite data layer
```

- [ ] **Step 6: Run make check**

Run: `make check`
Expected: PASS (no logic changes)

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/turn_orchestrator.py nanobot/config/schema.py nanobot/agent/loop.py nanobot/cli/memory.py nanobot/memory/graph/graph.py
git commit -m "docs: add size-exception comments to justified large files"
```

---

## Phase 2: Reduce __init__.py Exports (2 PRs)

### Task 2: Reduce agent/__init__.py from 15 to ≤12 exports

**Context:** No external code imports these 3 symbols via `nanobot.agent` (the package).
All consumers already import directly from submodules (`nanobot.agent.turn_types`,
`nanobot.agent.consolidation`, `nanobot.agent.streaming`). These are dead re-exports
that can be removed from `__init__.py` without any caller updates.

Symbols to remove:
- `TurnResult` — consumers import from `nanobot.agent.turn_types`
- `ConsolidationOrchestrator` — only used within agent/ package and tests (direct imports)
- `StreamingLLMCaller` — only used within agent/ package and tests (direct imports)

Also clean up: `turn_orchestrator.py` re-exports `TurnResult` and `TurnState` from
`turn_types.py` via `from nanobot.agent.turn_types import TurnResult as TurnResult`.
This re-export chain violates CLAUDE.md. Remove it if no caller depends on importing
`TurnResult` from `turn_orchestrator`.

**Files:**
- Modify: `nanobot/agent/__init__.py`
- Modify: `nanobot/agent/turn_orchestrator.py` (remove re-export annotations if safe)

- [ ] **Step 1: Verify no external code imports these 3 symbols via nanobot.agent**

Run:
```bash
grep -rn "from nanobot\.agent import" nanobot/ tests/ scripts/ --include="*.py" | grep -v "nanobot/agent/"
```

Confirm: no results reference `TurnResult`, `ConsolidationOrchestrator`, or
`StreamingLLMCaller`. If any do, update those imports first.

- [ ] **Step 2: Check for turn_orchestrator.py re-export chain**

Run:
```bash
grep -rn "from nanobot\.agent\.turn_orchestrator import TurnResult" nanobot/ tests/
```

If no results, the re-export in `turn_orchestrator.py` is dead — remove the
`as TurnResult` re-export annotation.

- [ ] **Step 3: Remove the 3 symbols from agent/__init__.py __all__**

Remove `TurnResult`, `ConsolidationOrchestrator`, `StreamingLLMCaller` from `__all__`
and their corresponding import statements.

- [ ] **Step 4: Run make check**

Run: `make check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor: reduce agent __init__.py exports from 15 to 12

Remove dead re-exports that no external code uses via the package-level
import. All consumers already import directly from submodules."
```

---

### Task 3: Reduce memory/__init__.py from 38 to ≤12 exports

**Context:** Only ~12 symbols are used by production code outside `nanobot/memory/`.
The other 26 exports are internal implementation details. This is the largest single
change in the plan — removing 26 symbols from `__all__`.

**Backward-compatibility aliases to remove:**
- `ProfileManager` (alias for `ProfileStore`) — used only within `memory/` internals
  via direct imports, not via `__init__.py`. Safe to remove from `__all__`.
- `CrossEncoderReranker` (alias for `OnnxCrossEncoderReranker`) — imported by
  `tests/test_reranker.py` via `from nanobot.memory import CrossEncoderReranker`.
  This test import must be updated to `from nanobot.memory.ranking.onnx_reranker import OnnxCrossEncoderReranker`.

**Scope warning:** The search in Step 1 may find more test files than expected. Every
symbol removed from `__all__` must be checked for external import usage. Budget time
for potentially updating 5-10 test files.

**Files:**
- Modify: `nanobot/memory/__init__.py`
- Modify: `tests/test_reranker.py` (known — update `CrossEncoderReranker` import)
- Modify: any other test files that import removed symbols from `nanobot.memory`

- [ ] **Step 1: Find all external imports from nanobot.memory**

Run:
```bash
grep -rn "from nanobot\.memory import" nanobot/ tests/ scripts/ --include="*.py" | grep -v "nanobot/memory/"
```

- [ ] **Step 2: Identify which of the 38 exports are used externally**

Cross-reference Step 1 results against `__all__`. Any symbol not imported externally
can be removed from `__all__`.

- [ ] **Step 3: Update test imports to use direct subdirectory paths**

For each test importing a removed symbol from `nanobot.memory`, update to import from
the actual module:
- `ConflictManager` → `from nanobot.memory.write.conflicts import ConflictManager`
- `MemoryRetriever` → `from nanobot.memory.read.retriever import MemoryRetriever`
- `ProfileStore` → `from nanobot.memory.persistence.profile_io import ProfileStore`
- `KnowledgeGraph` → `from nanobot.memory.graph.graph import KnowledgeGraph`
- (etc. — see Task 2 Step 1 results for full list)

- [ ] **Step 4: Reduce __all__ to only externally-used symbols**

Keep in `__all__` (≤12):
```python
__all__ = [
    "MemoryStore",
    "MemoryEvent",
    "BeliefRecord",
    "KnowledgeTriple",
    "Embedder",
    "LocalEmbedder",
    "HashEmbedder",
    "OpenAIEmbedder",
    "UnifiedMemoryDB",
    "ConsolidationPipeline",
    "MemoryMaintenance",
    "RolloutConfig",
]
```

Remove all other exports. Keep corresponding import statements only for the retained symbols.

- [ ] **Step 5: Run make check**

Run: `make check`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: reduce memory __init__.py exports from 38 to 12"
```

---

## Phase 3: Split Oversized Files (13 PRs)

Each file split is its own PR. Ordered by impact (largest files first, most-imported first).
Each follows the same pattern: extract a secondary concern into a new module, update imports,
verify with `make check`.

**Pre-split protocol (from CLAUDE.md):** Before each split, trace call paths crossing the
extraction boundary. Identify shared methods. Check for re-export chains.

**Documentation:** Each Phase 3 PR must update `docs/architecture.md` if it adds new files
to a documented package. CLAUDE.md requires documentation review before committing.

---

### Task 4: Split tools/builtin/excel.py (1102 LOC)

**Seams:** Excel reading/parsing vs. table analysis/transformation vs. multi-sheet coordination.

**Files:**
- Modify: `nanobot/tools/builtin/excel.py`
- Create: `nanobot/tools/builtin/excel_analysis.py` (table analysis + transformation logic)

- [ ] **Step 1: Read excel.py and identify extraction boundary**

Identify which classes/functions handle analysis vs. reading. Document the call paths
that cross the boundary.

- [ ] **Step 2: Extract analysis logic to excel_analysis.py**

Move table analysis functions and classes to the new file. Keep the Tool subclass
and reading logic in `excel.py`.

- [ ] **Step 3: Update imports in excel.py**

Import extracted symbols from `excel_analysis.py`.

- [ ] **Step 4: Run make check**

Run: `make check`
Expected: PASS

- [ ] **Step 5: Verify both files are ≤500 LOC**

Run: `wc -l nanobot/tools/builtin/excel.py nanobot/tools/builtin/excel_analysis.py`

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: split excel tool — extract analysis logic to excel_analysis.py"
```

---

### Task 5: Split memory/write/ingester.py (919 LOC)

**Seams:** Event coercion/validation vs. persistence orchestration.

**Files:**
- Modify: `nanobot/memory/write/ingester.py`
- Create: `nanobot/memory/write/event_validation.py` (coercion + validation logic)

- [ ] **Step 1: Read ingester.py and identify extraction boundary**
- [ ] **Step 2: Extract validation logic to event_validation.py**
- [ ] **Step 3: Update imports**
- [ ] **Step 4: Run make check** — Expected: PASS
- [ ] **Step 5: Verify both files ≤500 LOC**
- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: split ingester — extract event validation to event_validation.py"
```

---

### Task 6: Split memory/read/retriever.py (824 LOC)

**Seams:** Raw search execution vs. RRF fusion/scoring vs. graph augmentation.

**Files:**
- Modify: `nanobot/memory/read/retriever.py`
- Create: `nanobot/memory/read/search_fusion.py` (RRF fusion + scoring logic)

- [ ] **Step 1: Read retriever.py and identify extraction boundary**
- [ ] **Step 2: Extract fusion logic to search_fusion.py**
- [ ] **Step 3: Update imports**
- [ ] **Step 4: Run make check** — Expected: PASS
- [ ] **Step 5: Verify both files ≤500 LOC**
- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: split retriever — extract search fusion to search_fusion.py"
```

---

### Task 7: Split memory/persistence/profile_io.py (728 LOC)

**Seams:** Basic CRUD/snapshots vs. conflict detection/resolution.

**Files:**
- Modify: `nanobot/memory/persistence/profile_io.py`
- Create: `nanobot/memory/persistence/profile_conflicts.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split profile_io — extract conflict logic to profile_conflicts.py"
```

---

### Task 8: Split tools/builtin/powerpoint.py (670 LOC)

**Seams:** File I/O + slide enumeration vs. text extraction + layout analysis.

**Files:**
- Modify: `nanobot/tools/builtin/powerpoint.py`
- Create: `nanobot/tools/builtin/pptx_extraction.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split powerpoint tool — extract content parsing to pptx_extraction.py"
```

---

### Task 9: Split agent/message_processor.py (667 LOC)

**Seams:** Message classification/dispatch vs. function result handling.

**Files:**
- Modify: `nanobot/agent/message_processor.py`
- Create: `nanobot/agent/result_handler.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split message_processor — extract result handling to result_handler.py"
```

---

### Task 10: Split memory/read/context_assembler.py (608 LOC)

**Seams:** Budget calculation vs. section rendering vs. prompt assembly.

**Files:**
- Modify: `nanobot/memory/read/context_assembler.py`
- Create: `nanobot/memory/read/section_renderer.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split context_assembler — extract section rendering to section_renderer.py"
```

---

### Task 11: Split memory/write/conflicts.py (595 LOC)

**Seams:** Conflict detection/querying vs. interactive resolution.

**Files:**
- Modify: `nanobot/memory/write/conflicts.py`
- Create: `nanobot/memory/write/conflict_resolution.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split conflicts — extract resolution logic to conflict_resolution.py"
```

---

### Task 12: Split memory/graph/entity_classifier.py (590 LOC)

**Seams:** Individual classifiers (regex, keywords, suffixes) vs. multi-signal scoring.

**Files:**
- Modify: `nanobot/memory/graph/entity_classifier.py`
- Create: `nanobot/memory/graph/classification_signals.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split entity_classifier — extract signal implementations to classification_signals.py"
```

---

### Task 13: Split coordination/delegation.py (585 LOC)

**Seams:** Routing decisions vs. cycle detection vs. contract construction.

**Files:**
- Modify: `nanobot/coordination/delegation.py`
- Create: `nanobot/coordination/delegation_routing.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split delegation — extract routing logic to delegation_routing.py"
```

---

### Task 14: Split channels/telegram.py (583 LOC)

**Seams:** Telegram API client vs. markdown formatting/conversion.

**Files:**
- Modify: `nanobot/channels/telegram.py`
- Create: `nanobot/channels/telegram_formatting.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split telegram — extract formatting to telegram_formatting.py"
```

---

### Task 15: Split context/skills.py (521 LOC)

**Seams:** Skill discovery/scanning vs. caching/lifecycle vs. tool introspection.

**Files:**
- Modify: `nanobot/context/skills.py`
- Create: `nanobot/context/skill_discovery.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split skills — extract discovery logic to skill_discovery.py"
```

---

### Task 16: Split memory/write/extractor.py (510 LOC)

**Seams:** LLM extraction orchestration vs. heuristic fallback logic.

**Files:**
- Modify: `nanobot/memory/write/extractor.py`
- Create: `nanobot/memory/write/heuristic_extractor.py`

- [ ] **Step 1-6:** Same pattern as above.

```bash
git commit -m "refactor: split extractor — extract heuristic fallback to heuristic_extractor.py"
```

---

## Execution Order and Dependencies

```
Phase 1: Task 1 (size-exception comments) — no dependencies
    ↓
Phase 2: Task 2 (agent exports) → Task 3 (memory exports) — sequential
    ↓
Phase 3: Tasks 4-16 — independent, can be done in any order
         Recommended priority: largest files first (Tasks 4, 5, 6)
```

**Total PRs:** 16
**Risk level:** Low — all changes are structural (moves + import rewrites), no logic changes.
**Validation:** `make check` after every PR.

---

## Out of Scope

- Internal refactoring of module logic (e.g., simplifying ingester algorithms)
- Dependency inversion with Protocol interfaces at package boundaries
- CapabilityRegistry redesign
- Consolidation.py / consolidation_pipeline.py merge
- Any logic changes
- Cleaning up `ProfileManager` alias usage within `memory/` internals (5+ files use it;
  follow-up cleanup after this plan completes)
