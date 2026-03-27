# Rollout Config Elimination — Replace Dict-Based Feature Flags with MemoryConfig

> **Status:** Complete (PR #79, merged 2026-03-26)

**Goal:** Eliminate `RolloutConfig` and its flat `dict[str, Any]` rollout dict, replacing all consumers with direct typed access to `MemoryConfig` (Pydantic model).

**Architecture:** `RolloutConfig` was a dual-schema anti-pattern: `MemoryConfig` fields were manually mapped into a flat dict via `_config_to_overrides()` (20+ manual mappings), then consumers read from the dict with string-keyed `.get()` calls. The fix: consumers read directly from `MemoryConfig`. No mapping layer, no drift.

**Tech Stack:** Python 3.10+, Pydantic, pytest

---

## What was done

### Phase 1: Move graph_enabled into MemoryConfig
- Moved `graph_enabled` from `AgentConfig` to `MemoryConfig` (memory subsystem concern)
- Added config loader migration for existing config files with flat `graph_enabled`

### Phase 2: Add rollout_status() to MemoryConfig
- Added `rollout_status()` method returning the subset of fields relevant to reporting
- Replaces `RolloutConfig.get_status()`

### Phase 3: Remove dead code
- Removed unused `rollout_fn` callbacks from `EventIngester` and `MemoryMaintenance`
- These were stored but never called

### Phase 4: Migrate RetrievalScorer
- Replaced `rollout_fn: Callable[[], dict[str, Any]]` with `memory_config_fn: Callable[[], MemoryConfig]`
- `rerank_items()` reads `self._memory_config_fn().reranker.mode` instead of `self._rollout_fn().get("reranker_mode", "disabled")`

### Phase 5: Migrate EvalRunner
- Replaced two rollout dict callbacks with one `memory_config_fn`
- Gate thresholds and rollout mode read from typed fields

### Phase 6: Delete RolloutConfig
- Deleted `nanobot/memory/rollout.py` (175 LOC)
- `MemoryStore.__init__` reads directly from `self._memory_config`
- Added `memory_config` public property

### Results

| Metric | Before | After |
|--------|--------|-------|
| Files deleted | — | 3 (`rollout.py`, `test_rollout_config.py`, `test_memory_rollout_fn.py`) |
| LOC deleted (net) | — | ~540 |
| Manual mapping entries | 20+ | 0 |
| Untyped dict callbacks | 5 | 0 |
| String-keyed `.get()` calls | 12+ | 0 |
