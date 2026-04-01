# Fix Any Typing — Replace with Protocols

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all `Any`-typed parameters at extraction boundaries with Protocol types, restoring compile-time type safety that was lost during the Phase 4 file-split refactoring. Also replace all `assert` guards with proper `if/raise` checks.

**Architecture:** Define Protocol types in the consuming module (not a separate protocols.py file — each Protocol is small and used by one consumer). Each Protocol declares exactly the methods/attributes the consumer calls. Replace `assert` with `if ... is None: raise RuntimeError(...)`.

**Tech Stack:** Python 3.10+, `typing.Protocol`, ruff, mypy, pytest

**Key rule:** Per `.claude/rules/architecture-constraints.md`: *"Use Protocol types or dependency injection to invert the dependency if needed."*

---

## File Structure

### Files to Modify

| File | Change |
|------|--------|
| `nanobot/memory/persistence/belief_lifecycle.py` | `store: Any` → `store: _ProfileStoreProtocol` (9 functions) |
| `nanobot/memory/persistence/profile_io.py` | `_conflict_mgr: Any` → typed; `assert` → `if/raise` |
| `nanobot/memory/write/conflict_interaction.py` | `mgr: Any` → `mgr: _ConflictManagerProtocol` |
| `nanobot/memory/graph/graph_traversal.py` | `graph: Any` → `graph: _KnowledgeGraphProtocol`; `assert` → `if/raise` |
| `nanobot/memory/write/extractor.py` | `Any` callable params → `Callable[...]` types |
| `nanobot/memory/read/retriever.py` | `assert` → `if/raise` |
| `nanobot/memory/ranking/onnx_reranker.py` | `assert` → `if/raise` |
| `nanobot/memory/strategy_extractor.py` | `assert` → `if/raise` |

---

## Task 1: Define Protocol in belief_lifecycle.py and type `store` parameter

**Files:**
- Modify: `nanobot/memory/persistence/belief_lifecycle.py`

The Protocol needs these methods/attributes (traced from actual usage):

```python
class _ProfileStoreProtocol(Protocol):
    _MAX_EVIDENCE_REFS: int

    def read_profile(self) -> dict[str, Any]: ...
    def write_profile(self, profile: dict[str, Any]) -> None: ...
    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]: ...
    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]: ...
    def _touch_meta_entry(self, entry: dict[str, Any], **kwargs: Any) -> None: ...
    def _validate_profile_field(self, field: str) -> str: ...
```

- [ ] **Step 1:** Add the Protocol class at the top of `belief_lifecycle.py` (after imports, before `__all__`)
- [ ] **Step 2:** Replace `store: Any` with `store: _ProfileStoreProtocol` in all 9 function signatures
- [ ] **Step 3:** Run `make lint && make typecheck`
- [ ] **Step 4:** Run `PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`
- [ ] **Step 5:** Commit: `fix(memory): replace Any with Protocol in belief_lifecycle.py`

---

## Task 2: Type `_conflict_mgr` and `_corrector` in profile_io.py + replace assert with if/raise

**Files:**
- Modify: `nanobot/memory/persistence/profile_io.py`

ProfileStore calls 3 methods on `_conflict_mgr`:
- `_conflict_pair(old: str, new: str) -> bool`
- `_apply_profile_updates(profile, updates, *, enable_contradiction_check, source_event_ids) -> tuple[int, int, int]`
- `has_open_conflict(profile: dict, key: str) -> bool`

ProfileStore calls 1 method on `_corrector`:
- `apply_live_user_correction(content, channel, chat_id, enable_contradiction_check) -> dict`

- [ ] **Step 1:** Define `_ConflictManagerProtocol` and `_CorrectorProtocol` at the top of `profile_io.py`
- [ ] **Step 2:** Change `_conflict_mgr: Any | None` → `_conflict_mgr: _ConflictManagerProtocol | None`
- [ ] **Step 3:** Change `_corrector: Any | None` → `_CorrectorProtocol | None`
- [ ] **Step 4:** Change `set_conflict_mgr(self, conflict_mgr: Any)` → `set_conflict_mgr(self, conflict_mgr: _ConflictManagerProtocol)`
- [ ] **Step 5:** Change `set_corrector(self, corrector: Any)` → `set_corrector(self, corrector: _CorrectorProtocol)`
- [ ] **Step 6:** Replace 4 `assert` guards with `if ... is None: raise RuntimeError(...)`:
  - Lines 452, 464, 496: `assert self._conflict_mgr is not None` → `if self._conflict_mgr is None: raise RuntimeError("conflict_mgr not wired")`
  - Line 528: `assert self._corrector is not None` → same pattern
- [ ] **Step 7:** Run `make lint && make typecheck && make test`
- [ ] **Step 8:** Commit: `fix(memory): type conflict_mgr/corrector in ProfileStore, replace assert with if/raise`

---

## Task 3: Define Protocol in conflict_interaction.py and type `mgr` parameter

**Files:**
- Modify: `nanobot/memory/write/conflict_interaction.py`

The functions call these on `mgr`:
- `list_conflicts(include_closed: bool) -> list[ConflictRecord]`
- `profile_mgr.read_profile() -> dict`
- `profile_mgr.write_profile(profile) -> None`
- `resolve_conflict_details(index: int, action: str) -> dict`

- [ ] **Step 1:** Define `_ConflictManagerProtocol` with the 4 methods/attributes above
- [ ] **Step 2:** Replace `mgr: Any` with `mgr: _ConflictManagerProtocol` in 3 function signatures
- [ ] **Step 3:** Run `make lint && make typecheck && make test`
- [ ] **Step 4:** Commit: `fix(memory): replace Any with Protocol in conflict_interaction.py`

---

## Task 4: Define Protocol in graph_traversal.py and type `graph` parameter + replace assert

**Files:**
- Modify: `nanobot/memory/graph/graph_traversal.py`

The functions access:
- `graph.enabled` (bool property)
- `graph._db` (GraphStore | None)
- `graph._db.get_entity(name)`, `graph._db.get_edges_from(name)`, `graph._db.get_edges_to(name)`
- `graph._get_display_name(canonical)`
- `graph.get_neighbors(name, depth=depth)` (async)

- [ ] **Step 1:** Define `_KnowledgeGraphProtocol` with the needed surface area
- [ ] **Step 2:** Replace `graph: Any` with `graph: _KnowledgeGraphProtocol` in both functions
- [ ] **Step 3:** Replace `assert graph._db is not None` (line 50) with `if graph._db is None: raise RuntimeError(...)`
- [ ] **Step 4:** Run `make lint && make typecheck && make test`
- [ ] **Step 5:** Commit: `fix(memory): replace Any with Protocol in graph_traversal.py`

---

## Task 5: Type MemoryExtractor callable params + replace remaining asserts

**Files:**
- Modify: `nanobot/memory/write/extractor.py`
- Modify: `nanobot/memory/read/retriever.py`
- Modify: `nanobot/memory/ranking/onnx_reranker.py`
- Modify: `nanobot/memory/strategy_extractor.py`

- [ ] **Step 1:** In `extractor.py`, change constructor:
  ```python
  to_str_list: Any → to_str_list: Callable[[Any], list[str]]
  coerce_event: Any → coerce_event: Callable[..., MemoryEvent | None]
  utc_now_iso: Any → utc_now_iso: Callable[[], str]
  ```
- [ ] **Step 2:** Replace remaining `assert` guards with `if/raise` in:
  - `retriever.py:97-98` — `assert self._db is not None` / `assert self._embedder is not None`
  - `onnx_reranker.py:139-140` — `assert self._tokenizer is not None` / `assert self._session is not None`
  - `strategy_extractor.py:142` — `assert self._provider is not None`
- [ ] **Step 3:** Run `make lint && make typecheck && make test`
- [ ] **Step 4:** Commit: `fix(memory): type extractor callable params, replace all remaining assert guards`

---

## Task 6: Final verification + code review + PR

- [ ] **Step 1:** Verify zero `Any` at extraction boundaries: `grep -rn ": Any" nanobot/memory/persistence/belief_lifecycle.py nanobot/memory/write/conflict_interaction.py nanobot/memory/graph/graph_traversal.py`
- [ ] **Step 2:** Verify zero `assert` guards (except test files): `grep -rn "^        assert " nanobot/memory/ --include="*.py"`
- [ ] **Step 3:** Run `make pre-push`
- [ ] **Step 4:** Dispatch code review
- [ ] **Step 5:** Push and create PR
