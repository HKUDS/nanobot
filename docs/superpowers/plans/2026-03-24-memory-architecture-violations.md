# Memory Architecture Violations Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 6 architecture violations and key advisories in `nanobot/memory/` identified by architecture review.

**Architecture:** Targeted fixes to existing files — rename `helpers.py`, trim `__init__.py` exports, extract shared classification functions to break write→read coupling, add crash-barrier comments, and remove backward-compat static method aliases from `MemoryStore`. No new subsystem creation; no changes to the composition root pattern (V-04/V-05 are noted but deferred — `MemoryStore.__init__` as shadow composition root is a larger refactor that requires its own plan).

**Tech Stack:** Python 3.10+, ruff, mypy, pytest

**Scope note:** V-04 (shadow composition root) and V-05 (post-construction private attribute wiring) are architectural debt that require a dedicated refactoring plan to extract `MemoryStore.__init__` construction into `agent_factory.py`. They are out of scope for this PR to keep changes reviewable.

---

### Task 1: Rename `helpers.py` → `_text.py` (V-01)

CLAUDE.md prohibits files named `helpers.py`. The file contains text normalization, timestamp helpers, token estimation, and graph query keyword extraction. Since 8 of 10 functions are text/string operations, rename to `_text.py` (leading underscore = package-private). Move graph keyword extraction (`_extract_query_keywords`, `_GRAPH_QUERY_STOPWORDS`) to `graph/` where it belongs.

**Files:**
- Rename: `nanobot/memory/helpers.py` → `nanobot/memory/_text.py`
- Create: `nanobot/memory/graph/_keywords.py` (graph keyword extraction)
- Modify: `nanobot/memory/graph/graph.py` (import from `_keywords` instead of `helpers`)
- Modify: All files importing from `helpers` (8 files + `store.py`)
- Modify: `nanobot/eval/memory_eval.py` (imports from `nanobot.memory.helpers`)
- Modify: `tests/test_memory_helpers.py` (update imports)

- [ ] **Step 1: Create `nanobot/memory/graph/_keywords.py`**

Extract `_GRAPH_QUERY_STOPWORDS` and `_extract_query_keywords` from `helpers.py`:

```python
"""Graph query keyword extraction."""

from __future__ import annotations

import re

_GRAPH_QUERY_STOPWORDS: frozenset[str] = frozenset({
    # ... (copy the full set from helpers.py)
})


def _extract_query_keywords(query: str) -> set[str]:
    """Extract significant keywords from a query for graph entity lookup."""
    tokens = {t for t in re.findall(r"[a-zA-Z0-9_\\-]+", query.lower()) if len(t) > 2}
    return tokens - _GRAPH_QUERY_STOPWORDS
```

- [ ] **Step 2: Rename `helpers.py` → `_text.py`**

```bash
git mv nanobot/memory/helpers.py nanobot/memory/_text.py
```

Remove `_GRAPH_QUERY_STOPWORDS` and `_extract_query_keywords` from `_text.py` (they now live in `graph/_keywords.py`).

- [ ] **Step 3: Update all internal imports**

Replace `from ..helpers import` / `from .helpers import` with `from .._text import` / `from ._text import` in these files:
- `nanobot/memory/store.py`
- `nanobot/memory/consolidation_pipeline.py`
- `nanobot/memory/maintenance.py`
- `nanobot/memory/unified_db.py`
- `nanobot/memory/read/retriever.py`
- `nanobot/memory/read/context_assembler.py`
- `nanobot/memory/persistence/profile_io.py`
- `nanobot/memory/persistence/snapshot.py`
- `nanobot/memory/write/conflicts.py`
- `nanobot/memory/write/ingester.py`

For `store.py`, also update imports of `_GRAPH_QUERY_STOPWORDS` and `_extract_query_keywords` to come from `graph._keywords`.

- [ ] **Step 4: Update external imports**

- `nanobot/eval/memory_eval.py`: change `from nanobot.memory.helpers import` → `from nanobot.memory._text import`
- `tests/test_memory_helpers.py`: change `from nanobot.memory.helpers import` → `from nanobot.memory._text import` (also update graph keyword imports to come from `nanobot.memory.graph._keywords`)

- [ ] **Step 5: Update `__init__.py` docstring**

Replace `- **helpers.py** — Utility functions` with `- **_text.py** — Text normalization, timestamp, and coercion helpers`

- [ ] **Step 6: Verify**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: rename memory/helpers.py to _text.py, extract graph keywords (V-01)"
```

---

### Task 2: Extract shared classifiers to break write→read coupling (A-05/A-09)

`write/ingester.py` imports `ContextAssembler._is_resolved_task_or_decision` and `RetrievalPlanner.memory_type_for_item` from `read/`. These are classification functions that both paths need. Move them to a neutral location.

**Files:**
- Modify: `nanobot/memory/event.py` — add `is_resolved_task_or_decision()` and `memory_type_for_item()` as module-level functions
- Modify: `nanobot/memory/read/context_assembler.py` — delegate to `event.py` function
- Modify: `nanobot/memory/read/retrieval_planner.py` — delegate to `event.py` function
- Modify: `nanobot/memory/read/retriever.py` — import from `event.py`
- Modify: `nanobot/memory/write/ingester.py` — import from `event.py` instead of `read/`

- [ ] **Step 1: Add shared classifiers to `event.py`**

Add to `nanobot/memory/event.py`:

```python
MEMORY_TYPES: frozenset[str] = frozenset({"semantic", "episodic", "reflection"})

_RESOLVED_MARKERS: tuple[str, ...] = (
    "done", "completed", "resolved", "closed", "finished", "cancelled", "canceled",
)


def is_resolved_task_or_decision(summary: str) -> bool:
    """Check whether a task/decision summary indicates resolved status."""
    text = summary.lower()
    return any(marker in text for marker in _RESOLVED_MARKERS)


def memory_type_for_item(item: dict[str, Any]) -> str:
    """Classify the memory type of an event/item dict."""
    memory_type = str(item.get("memory_type", "")).strip().lower()
    if memory_type in MEMORY_TYPES:
        return memory_type
    meta = item.get("metadata")
    if isinstance(meta, dict):
        meta_type = str(meta.get("memory_type", "")).strip().lower()
        if meta_type in MEMORY_TYPES:
            return meta_type
    event_type = str(item.get("type", "")).strip().lower()
    if event_type in {"task", "decision"}:
        return "episodic"
    if event_type in {"preference", "fact", "constraint", "relationship"}:
        return "semantic"
    return "episodic"
```

- [ ] **Step 2: Update `write/ingester.py`**

Remove the two imports from `read/`:
```python
# REMOVE these lines:
from ..read.context_assembler import ContextAssembler
from ..read.retrieval_planner import RetrievalPlanner
```

Add:
```python
from ..event import is_resolved_task_or_decision, memory_type_for_item
```

Replace usages:
- `ContextAssembler._is_resolved_task_or_decision(summary)` → `is_resolved_task_or_decision(summary)`
- `RetrievalPlanner.memory_type_for_item(...)` → `memory_type_for_item(...)`

- [ ] **Step 3: Update `read/context_assembler.py`**

Replace inline `_is_resolved_task_or_decision` static method with a delegate:

```python
from ..event import is_resolved_task_or_decision
```

Replace call at line 382: `self._is_resolved_task_or_decision(summary)` → `is_resolved_task_or_decision(summary)`

Keep the static method as a thin delegate for any external callers:
```python
_is_resolved_task_or_decision = staticmethod(is_resolved_task_or_decision)
```

- [ ] **Step 4: Update `read/retrieval_planner.py`**

Import from event.py and delegate:

```python
from ..event import memory_type_for_item as _memory_type_for_item
```

Replace the `memory_type_for_item` static method body to delegate:
```python
@staticmethod
def memory_type_for_item(item: dict[str, Any]) -> str:
    return _memory_type_for_item(item)
```

Also update `MEMORY_TYPES` constant to import from `event.py` if it's duplicated.

- [ ] **Step 5: Update `read/retriever.py`**

The retriever calls `RetrievalPlanner.memory_type_for_item(item)` — these can stay as-is since the planner delegates. No changes needed unless we want direct imports (optional).

- [ ] **Step 6: Verify**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: extract shared classifiers to event.py, break write→read coupling (A-05)"
```

---

### Task 3: Trim `__init__.py` exports from 38 to ≤12 (V-03)

Most consumers only import `MemoryStore`. Internal types should be imported from their owning subpackages. Remove duplicate aliases and implementation details from `__all__`.

**Files:**
- Modify: `nanobot/memory/__init__.py`
- Modify: `tests/test_reranker.py` (only external user of `CrossEncoderReranker` alias)

- [ ] **Step 1: Update `tests/test_reranker.py`**

Change:
```python
from nanobot.memory import CrossEncoderReranker
```
To:
```python
from nanobot.memory.ranking.onnx_reranker import OnnxCrossEncoderReranker as CrossEncoderReranker
```

- [ ] **Step 2: Rewrite `nanobot/memory/__init__.py`**

Keep only facade-level exports that external callers actually need:

```python
from .embedder import Embedder, HashEmbedder, LocalEmbedder, OpenAIEmbedder
from .event import MemoryEvent
from .store import MemoryStore
from .unified_db import UnifiedMemoryDB

__all__ = [
    "Embedder",
    "HashEmbedder",
    "LocalEmbedder",
    "MemoryEvent",
    "MemoryStore",
    "OpenAIEmbedder",
    "UnifiedMemoryDB",
]
```

Remove all other imports — consumers of graph types, ranking, write/read internals should import from subpackages directly. Remove the `ProfileManager` and `CrossEncoderReranker` duplicate aliases entirely.

- [ ] **Step 3: Fix any broken imports across the codebase**

Search for `from nanobot.memory import X` where X is no longer in `__all__`. Update callers to import from the specific submodule. Based on grep results, no external callers import removed symbols except the test fixed in step 1.

- [ ] **Step 4: Verify**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: trim memory/__init__.py exports from 38 to 7 (V-03)"
```

---

### Task 4: Add crash-barrier comment to `embedder.py` (V-06)

**Files:**
- Modify: `nanobot/memory/embedder.py:113`

- [ ] **Step 1: Fix the bare except**

At line 113 in `embedder.py`, the `except Exception` re-raises after logging. Since it re-raises, a narrower exception isn't strictly needed, but the crash-barrier comment is required:

```python
            except Exception:  # crash-barrier: ONNX/tokenizer load can fail in many ways
                logger.exception("Failed to load local ONNX embedder")
                raise
```

- [ ] **Step 2: Verify**

```bash
make lint && make typecheck
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "fix: add crash-barrier annotation to embedder.py (V-06)"
```

---

### Task 5: Remove backward-compat static method aliases from `MemoryStore` (A-03)

`MemoryStore` re-exports 10 helper functions as static methods and 4 class-level constant aliases for backward compatibility. This inflates the god-class surface. Remove them and fix any callers.

**Files:**
- Modify: `nanobot/memory/store.py` (remove lines 315-334)
- Modify: `tests/test_store_helpers.py` (update `MemoryStore._to_datetime` → direct import)

- [ ] **Step 1: Update test callers**

In `tests/test_store_helpers.py`, change:
```python
MemoryStore._to_datetime("2026-01-01T00:00:00Z")
```
To:
```python
from nanobot.memory._text import _to_datetime
# ...
_to_datetime("2026-01-01T00:00:00Z")
```

- [ ] **Step 2: Remove static method aliases from `store.py`**

Delete lines 315-334 (the block of `staticmethod` assignments and class constant aliases). Also remove the corresponding imports from helpers that are no longer used in `store.py` itself.

- [ ] **Step 3: Remove unused imports from `store.py`**

After removing the aliases, these imports from `_text` are no longer needed in `store.py` (unless used elsewhere in the file): `_GRAPH_QUERY_STOPWORDS`, `_contains_any`, `_estimate_tokens`, `_extract_query_keywords`, `_norm_text`, `_safe_float`, `_to_datetime`, `_to_str_list`, `_tokenize`, `_utc_now_iso`. Check which are actually used in `store.py` methods before removing.

- [ ] **Step 4: Verify**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: remove backward-compat static method aliases from MemoryStore (A-03)"
```

---

### Task 6: Move `EvalRunner` import behind TYPE_CHECKING (A-01)

`store.py` has a runtime import from `nanobot.eval` — evaluation tooling should not be coupled to the domain subsystem at import time.

**Files:**
- Modify: `nanobot/memory/store.py`

- [ ] **Step 1: Move import to TYPE_CHECKING block**

Move `from nanobot.eval.memory_eval import EvalRunner` into the `if TYPE_CHECKING:` block. Add a lazy import inside `__init__` where `EvalRunner` is constructed:

```python
# At construction site (line ~263):
from nanobot.eval.memory_eval import EvalRunner
self.eval_runner = EvalRunner(...)
```

This keeps the runtime import localized to the construction point rather than module-level.

- [ ] **Step 2: Verify**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "refactor: lazy-import EvalRunner to decouple memory from eval (A-01)"
```

---

### Task 7: Final validation

- [ ] **Step 1: Run full check suite**

```bash
make check
```

- [ ] **Step 2: Verify export count**

```bash
python -c "import nanobot.memory; print(len(nanobot.memory.__all__))"
```

Expected: ≤ 12

- [ ] **Step 3: Verify no helpers.py exists**

```bash
test ! -f nanobot/memory/helpers.py && echo "PASS: helpers.py removed"
```

- [ ] **Step 4: Verify no write→read imports**

```bash
grep -r "from ..read" nanobot/memory/write/ || echo "PASS: no write→read imports"
```
