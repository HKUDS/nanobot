# Design: Memory Subsystem Completion

**Date:** 2026-03-23
**Status:** Draft
**Scope:** Four deferred items from `2026-03-22-store-refinement-design.md` — profile split,
`TokenBudgetAllocator`, `ProfileCache` + graph memoization, structured consolidation
**Out of scope:** `ContextAssembler` section-renderer extraction, changes outside
`nanobot/agent/memory/` and `nanobot/agent/consolidation.py`, provider/channel changes

---

## Problem

PR #34 (store-refinement) completed the `MemoryStore` facade and subsystem extraction but
explicitly deferred four items:

1. **`profile.py` is 980 lines** doing three jobs: profile I/O + belief CRUD, conflict
   detection, and live-correction orchestration. The `_store` back-reference elimination that
   blocked the split was completed in PR #34 — the blocker is gone.

2. **`context_assembler.py` token budget logic is untestable in isolation.** 65 lines of
   static priority weights (`_SECTION_PRIORITY_WEIGHTS`) plus allocation logic are inlined
   into `ContextAssembler.build()`. No way to unit-test the budget calculation without
   constructing a full `ContextAssembler` with all 8 callable injections.

3. **`ProfileManager.read_profile()` hits disk on every call.** Up to 10 reads per
   consolidation turn with no caching. The mtime-cache pattern is already proven by
   `EventIngester` — it just wasn't applied here. Graph entity traversal has the same
   problem: `_collect_graph_entity_names` does a full traversal on every retrieval call with
   no per-request memoization.

4. **`ConsolidationOrchestrator` has fragile lock management.** `WeakValueDictionary` +
   manual `prune_lock()` calls are a GC race waiting to happen. Background consolidation
   state (`_consolidating`, `_consolidation_tasks`, `_consolidation_sem`) is duplicated in
   both `MessageProcessor.__init__` (lines 93–95) and `AgentLoop._wire_memory()` (lines
   413–415). `fallback_archive_snapshot` directly accesses `MemoryPersistence` internals.

---

## Solution Overview

Four targeted changes, each with clean boundaries:

| Change | Files | What stays the same |
|--------|-------|---------------------|
| Split `profile.py` | `profile.py` → `profile_io.py` + `profile_correction.py`; `conflicts.py` extended | `MemoryStore` public API |
| `TokenBudgetAllocator` + config | `token_budget.py` (new); `context_assembler.py` simplified; `config/schema.py` extended | `ContextAssembler.build()` signature |
| `ProfileCache` + graph memoization | `profile_io.py`; `retriever.py` | All callers |
| Structured consolidation | `consolidation.py` rewritten; `message_processor.py` simplified | `MessageProcessor.process()` call sites |

Nothing outside `nanobot/agent/memory/` and `nanobot/agent/consolidation.py` changes
except `config/schema.py` (new `MemorySectionWeights` model) and `message_processor.py`
(consolidation submission simplified).

---

## Section 1: Target File Structure

| Action | File | Lines (est.) | Responsibility |
|--------|------|-------------|----------------|
| Replace | `nanobot/agent/memory/profile.py` | — | Deleted; replaced by two modules below |
| Create | `nanobot/agent/memory/profile_io.py` | ~420 | `ProfileStore`: read/write `profile.json`, belief CRUD, meta sidecar, `ProfileCache` |
| Create | `nanobot/agent/memory/profile_correction.py` | ~180 | `CorrectionOrchestrator`: live-correction pipeline |
| Extend | `nanobot/agent/memory/conflicts.py` | ~600 | `ConflictManager` gains `apply_profile_updates`, `_conflict_pair`, `_has_open_conflict` |
| Create | `nanobot/agent/memory/token_budget.py` | ~120 | `TokenBudgetAllocator`, `SectionBudget`, `DEFAULT_SECTION_WEIGHTS` |
| Modify | `nanobot/agent/memory/context_assembler.py` | ~560 | Removes inline budget logic; injects `TokenBudgetAllocator` |
| Modify | `nanobot/agent/memory/retriever.py` | ~1110 | Adds `_graph_cache` reset per `retrieve()` call |
| Modify | `nanobot/agent/consolidation.py` | ~160 | Full rewrite: `asyncio.TaskGroup`, context-manager API, `archive_fn` injection |
| Modify | `nanobot/config/schema.py` | +30 | `MemorySectionWeights`, `memory_section_weights` field on `AgentDefaults` |

**No changes to:** `ingester.py`, `extractor.py`, `snapshot.py`, `mem0_adapter.py`,
`reranker.py`, `event.py`, `persistence.py`, or any channel/provider/agent module.
`store.py` changes are limited to: updating the import of `ProfileStore` from
`profile_io` (replacing `ProfileManager` from `profile`), and updating `__init__` and
`_ensure_assembler` to wire `TokenBudgetAllocator`.

---

## Section 2: `ProfileStore` and `ProfileCache`

**Location:** `nanobot/agent/memory/profile_io.py`

### `ProfileCache`

A standalone cache object with an explicit invalidation contract. Write and invalidate are
coupled by design — `write()` updates the cache atomically so a write-then-read within the
same process never returns stale data.

```python
@dataclass(slots=True)
class ProfileCache:
    """Mtime-aware cache for profile.json. Owned exclusively by ProfileStore."""
    _path: Path
    _persistence: MemoryPersistence
    _data: dict[str, Any] | None = field(default=None, init=False)
    _mtime: float = field(default=-1.0, init=False)

    def read(self) -> dict[str, Any]:
        """Return cached data if file is unchanged, else reload from disk."""
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return {}
        if self._data is not None and mtime == self._mtime:
            return self._data
        self._data = self._persistence.read_json(self._path) or {}
        self._mtime = mtime
        return self._data

    def write(self, data: dict[str, Any]) -> None:
        """Write to disk and update cache atomically."""
        self._persistence.write_json(self._path, data)
        self._data = data
        try:
            self._mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = -1.0

    def invalidate(self) -> None:
        """Force next read() to reload from disk."""
        self._data = None
        self._mtime = -1.0
```

### `ProfileStore`

Replaces `ProfileManager`. Owns all profile I/O, belief CRUD, meta sidecar operations.
Uses `ProfileCache` internally — callers never interact with the cache directly.

```python
class ProfileStore:
    def __init__(
        self,
        *,
        profile_file: Path,
        persistence: MemoryPersistence,
        norm_text: Callable[[str], str],
    ) -> None:
        self._cache = ProfileCache(_path=profile_file, _persistence=persistence)
        ...

    def read_profile(self) -> dict[str, Any]:
        return self._cache.read()

    def write_profile(self, profile: dict[str, Any]) -> None:
        self._cache.write(profile)

    # Belief CRUD — add_belief, update_belief, retract_belief, verify_beliefs
    # Meta sidecar — _meta_section, _meta_entry, _touch_meta_entry
    # Pins/outdated — set_item_pin, mark_item_outdated
```

`ProfileStore` is **not** exported from `nanobot/agent/__init__.py` — it is an internal
subsystem detail. `MemoryStore` and test files import it directly from
`nanobot.agent.memory.profile_io`.

`profile.py` is deleted. `nanobot/agent/memory/__init__.py` updates its re-exports.

---

## Section 3: `CorrectionOrchestrator`

**Location:** `nanobot/agent/memory/profile_correction.py`

Owns `apply_live_user_correction` and its inner helpers. Receives all dependencies via
constructor injection — no back-references.

```python
class CorrectionOrchestrator:
    def __init__(
        self,
        *,
        profile_store: ProfileStore,
        extractor: MemoryExtractor,
        ingester: EventIngester,
        conflict_mgr: ConflictManager,
        snapshot: MemorySnapshot,
    ) -> None: ...

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]: ...
```

The signature is **synchronous** — it matches the existing
`ProfileManager.apply_live_user_correction` exactly.

**Delegation chain:** `MessageProcessor._pre_turn_memory` calls
`memory_store.profile_mgr.apply_live_user_correction(content, ...)`. After the refactor,
`profile_mgr` is a `ProfileStore` instance. `ProfileStore` exposes
`apply_live_user_correction` as a facade that delegates to its internal
`CorrectionOrchestrator`:

```python
class ProfileStore:
    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        return self._corrector.apply_live_user_correction(
            content, channel=channel, chat_id=chat_id,
            enable_contradiction_check=enable_contradiction_check,
        )
```

`MessageProcessor` is **unchanged** — it keeps calling
`memory_store.profile_mgr.apply_live_user_correction(...)`. No call-site changes in
`store.py`, `message_processor.py`, or any other module.

---

## Section 4: Conflict Detection Moves to `ConflictManager`

**Location:** `nanobot/agent/memory/conflicts.py`

Three methods move from `profile.py` into `ConflictManager`:

- `_conflict_pair(old_value: str, new_value: str) -> bool` (returns `True` if the two values conflict)
- `apply_profile_updates(profile: dict[str, Any], updates: dict[str, list[str]], *, enable_contradiction_check: bool, source_event_ids: list[str] | None = None) -> tuple[int, int, int]` (was `_apply_profile_updates`; 3-tuple is `(added, conflicts, touched)`)
- `has_open_conflict(profile: dict[str, Any], key: str) -> bool` (was `_has_open_conflict`)

`ProfileStore` calls `self._conflict_mgr.apply_profile_updates(...)` where it previously
called the inline methods. `ConflictManager` receives a `ProfileStore` reference via
constructor injection: its existing `profile_mgr: ProfileManager` constructor parameter is
renamed to `profile_store: ProfileStore`.

When `_apply_profile_updates` is moved to `ConflictManager.apply_profile_updates`, all
calls inside the method body that currently reference `self.*` (because they are on
`ProfileManager`) must be re-prefixed as `self.profile_store.*` — specifically:
`_to_str_list`, `_meta_entry`, `_touch_meta_entry`, `_add_belief_to_profile`,
`_update_belief_in_profile`, `_norm_text`, `PROFILE_KEYS`, `PROFILE_STATUS_ACTIVE`,
`PROFILE_STATUS_STALE`. The exception is `self._conflict_pair(...)` which is also
moved to `ConflictManager` and therefore remains `self._conflict_pair(...)`.

`ConflictManager.resolve_conflict_details` calls the following internal methods on
`self.profile_mgr`: `_validate_profile_field`, `_to_str_list`, `_find_mem0_id_for_text`,
`_meta_entry`, `_update_belief_in_profile`, and uses the class attributes
`PROFILE_STATUS_ACTIVE` / `PROFILE_STATUS_STALE`. All of these methods and attributes
are moved from `ProfileManager` to `ProfileStore` unchanged as part of this split —
`ProfileStore` is a rename-and-split of `ProfileManager`, not a new narrower API.
`ConflictManager` code using `self.profile_mgr.*` compiles without changes after the
parameter rename.

---

## Section 5: `TokenBudgetAllocator` and Config

### `token_budget.py`

**Location:** `nanobot/agent/memory/token_budget.py`

Pure, stateless. No I/O, no subsystem dependencies.

```python
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

# Default weights — mirrors _SECTION_PRIORITY_WEIGHTS from context_assembler.py.
# Keys are intent strings from RetrievalPlanner.infer_retrieval_intent().
DEFAULT_SECTION_WEIGHTS: dict[str, dict[str, float]] = {
    "fact_lookup":        {"long_term": 0.28, "profile": 0.23, "semantic": 0.20,
                           "episodic": 0.05, "reflection": 0.00, "graph": 0.19, "unresolved": 0.05},
    "debug_history":      {"long_term": 0.15, "profile": 0.10, "semantic": 0.10,
                           "episodic": 0.35, "reflection": 0.05, "graph": 0.15, "unresolved": 0.10},
    "planning":           {"long_term": 0.15, "profile": 0.15, "semantic": 0.20,
                           "episodic": 0.20, "reflection": 0.05, "graph": 0.15, "unresolved": 0.10},
    "reflection":         {"long_term": 0.15, "profile": 0.10, "semantic": 0.15,
                           "episodic": 0.10, "reflection": 0.25, "graph": 0.15, "unresolved": 0.10},
    "constraints_lookup": {"long_term": 0.19, "profile": 0.28, "semantic": 0.24,
                           "episodic": 0.05, "reflection": 0.00, "graph": 0.19, "unresolved": 0.05},
    "rollout_status":     {"long_term": 0.25, "profile": 0.15, "semantic": 0.30,
                           "episodic": 0.00, "reflection": 0.00, "graph": 0.20, "unresolved": 0.10},
    "conflict_review":    {"long_term": 0.15, "profile": 0.20, "semantic": 0.20,
                           "episodic": 0.15, "reflection": 0.00, "graph": 0.20, "unresolved": 0.10},
}

class TokenBudgetAllocator:
    def __init__(self, weights: dict[str, dict[str, float]]) -> None:
        self._weights = weights

    def allocate(self, total_tokens: int, intent: str) -> SectionBudget:
        """
        Normalise intent weights and allocate token budget per section.

        Falls back to 'fact_lookup' weights for unknown intents.
        Enforces a floor of 0 tokens per section (negative budgets are clamped).
        """
        ...
```

`TokenBudgetAllocator` is exported from `nanobot.agent.memory` for test access.

### Config schema

**Location:** `nanobot/config/schema.py`

```python
class MemorySectionWeights(BaseModel):
    """Per-section token budget weights for one retrieval intent.

    All values must be >= 0. They are normalised to sum to 1.0 at allocation
    time, so absolute magnitudes do not matter — only relative ratios.
    """
    long_term: float = Field(default=0.0, ge=0.0)
    profile: float = Field(default=0.0, ge=0.0)
    semantic: float = Field(default=0.0, ge=0.0)
    episodic: float = Field(default=0.0, ge=0.0)
    reflection: float = Field(default=0.0, ge=0.0)
    graph: float = Field(default=0.0, ge=0.0)
    unresolved: float = Field(default=0.0, ge=0.0)
```

Added to `AgentDefaults`:

```python
memory_section_weights: dict[str, MemorySectionWeights] = Field(default_factory=dict)
```

An empty dict means "use `DEFAULT_SECTION_WEIGHTS` from `token_budget.py`" — existing
deployments with no `memory_section_weights` in their config are unaffected.

`MemoryStore` merges config overrides on top of `DEFAULT_SECTION_WEIGHTS` before
constructing `TokenBudgetAllocator`:

```python
weights = {**DEFAULT_SECTION_WEIGHTS}
for intent, override in config.memory_section_weights.items():
    weights[intent] = override.model_dump()
self._budget_allocator = TokenBudgetAllocator(weights)
```

`ContextAssembler.__init__` gains a new required keyword parameter:
`budget_allocator: TokenBudgetAllocator`. It calls `self._budget.allocate(budget, intent)`
instead of `self._allocate_section_budgets(budget, intent, section_sizes)`. The old
`_SECTION_PRIORITY_WEIGHTS` class variable and `_allocate_section_budgets` `@classmethod`
are deleted.

**Note:** The existing `_allocate_section_budgets` is a `@classmethod` with a
`section_sizes: dict[str, int]` argument that caps per-section allocations at actual
content size (two-pass proportional algorithm). `TokenBudgetAllocator.allocate()` omits
this cap and performs simple proportional allocation. This is an intentional simplification
— the cap is a premature optimization that complicates testing. The `SectionBudget`
returned by `allocate()` represents the maximum each section *may* use; sections that
have less content simply return fewer tokens to the caller.

`ContextAssembler` is constructed in two places in `store.py` — both must pass the
`budget_allocator`:

1. `MemoryStore.__init__` (line 129): `ContextAssembler(profile_mgr=..., ...,
   budget_allocator=self._budget_allocator)`
2. `MemoryStore._ensure_assembler()` (line 320): same, using the same
   `self._budget_allocator` instance

`MemoryStore` constructs `_budget_allocator` once in `__init__` before constructing the
assembler, so both sites share the same allocator instance.

**Test migration:** `tests/test_memory_metadata_policy.py` calls
`ContextAssembler._allocate_section_budgets(budget, intent, sizes)` directly (lines 584,
609, 627). These tests must be rewritten as part of Step 4:

- The three call sites migrate to `TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS).allocate(budget, intent)`.
- `SectionBudget` is a frozen dataclass (`slots=True`) — subscript access like
  `alloc["long_term"]` must be rewritten to attribute access `alloc.long_term`.
- The existing tests `test_allocate_section_budgets_caps_at_actual_size` and
  `test_allocate_section_budgets_redistributes_surplus` test the two-pass cap algorithm
  which is intentionally removed. These tests must be replaced with new tests that verify
  simple proportional allocation behaviour of `TokenBudgetAllocator.allocate()`.
  Add tests for: proportional allocation, unknown intent falls back to `fact_lookup`,
  config override merging.

---

## Section 6: Graph Memoization

**Location:** `nanobot/agent/memory/retriever.py`

`MemoryRetriever` gains a `_graph_cache: dict[frozenset[str], set[str]]` instance variable.
It is initialized to `{}` in `MemoryRetriever.__init__` **and** reset at the entry of
every `retrieve()` call — request-scoped, not process-scoped, to prevent stale data
across turns.

```python
# In __init__:
self._graph_cache: dict[frozenset[str], set[str]] = {}

# In retrieve():
async def retrieve(self, query: str, ...) -> RetrievalResult:
    self._graph_cache = {}   # fresh per request
    ...
```

`_collect_graph_entity_names(self, query: str, events: list[dict[str, Any]])` computes
`query_entities` (a `set[str]`) from the query string early in the method, then checks
`self._graph_cache` before calling `KnowledgeGraph.get_related_entity_names_sync`:

```python
cache_key = frozenset(query_entities)
if cache_key in self._graph_cache:
    # Return full result (graph_entity_names already built from triples + graph)
    return self._graph_cache[cache_key]
# ...existing triple-scan + graph-traversal logic...
result = graph_entity_names | graph_related
self._graph_cache[cache_key] = result
return result
```

The cache key is `frozenset(query_entities)` — not the raw `query` string — because
`query_entities` is the actual input to the expensive graph traversal. The `events`
argument is **safe to exclude from the key** because the cache is reset at the start of
every `retrieve()` call: within a single call, the same `events` list is passed on every
invocation of `_collect_graph_entity_names`, making `query_entities` alone sufficient to
identify distinct calls.

Same `query_entities` within one retrieval call hits the cache; the next turn starts clean.
No TTL management, no stale data risk.

---

## Section 7: `ConsolidationOrchestrator` — Structured Concurrency

**Location:** `nanobot/agent/consolidation.py`

Full rewrite. Three changes:

### 7.1 Context-manager lifecycle

`ConsolidationOrchestrator` becomes an async context manager. `AgentLoop.__init__`
constructs it; `AgentLoop.run()` enters it with `async with self._consolidator:` wrapping
the main while loop. When the loop exits (on `stop()`), the `async with` block's
`__aexit__` drains pending tasks cleanly. **`stop()` remains synchronous** — it only sets
the stop flag; the drain happens naturally as `run()` unwinds.

```python
class ConsolidationOrchestrator:
    def __init__(
        self,
        *,
        memory: MemoryStore,
        archive_fn: Callable[[list[dict[str, Any]]], None],
        max_concurrent: int = 3,
        memory_window: int = 50,
        enable_contradiction_check: bool = True,
    ) -> None:
        self._memory = memory
        self._archive_fn = archive_fn
        self._max_concurrent = max_concurrent
        self._memory_window = memory_window
        self._enable_contradiction_check = enable_contradiction_check
        self._locks: dict[str, asyncio.Lock] = {}
        self._in_progress: set[str] = set()   # deduplication guard
        self._sem: asyncio.Semaphore | None = None
        self._tg: asyncio.TaskGroup | None = None

    async def __aenter__(self) -> ConsolidationOrchestrator:
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._tg = asyncio.TaskGroup()
        await self._tg.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._tg is not None:
            await self._tg.__aexit__(*exc_info)
```

### 7.2 `submit()` and `consolidate_and_wait()`

Two entry points replace the old `get_lock()` / `consolidate()` / `prune_lock()` trio:

**`submit()`** — fire-and-forget background consolidation. Replaces the current
`_consolidation_tasks`/`_consolidation_sem`/`_consolidating` pattern in
`MessageProcessor._consolidate_memory`.

**`consolidate_and_wait()`** — awaitable blocking consolidation used by
`_handle_slash_new`, which needs to wait for the result before clearing the session. This
replaces the current `get_lock()` + `consolidate()` + `prune_lock()` sequence in
`_handle_slash_new`.

```python
def submit(
    self,
    session_key: str,
    session: Session,
    provider: ChatProvider,
    model: str,
) -> None:
    """Schedule a background consolidation task. Returns immediately.

    Silently skips if a consolidation for this session is already in progress,
    preserving the deduplication behaviour previously in MessageProcessor._consolidating.
    """
    assert self._tg is not None, "must be used as async context manager"
    if session_key in self._in_progress:
        return
    self._in_progress.add(session_key)
    self._tg.create_task(self._run(session_key, session, provider, model))

async def consolidate_and_wait(
    self,
    session_key: str,
    session: Session,
    provider: ChatProvider,
    model: str,
    *,
    archive_all: bool = False,
) -> bool:
    """Run consolidation inline (awaitable). Returns True on success.

    Used by _handle_slash_new which must complete consolidation before
    clearing the session. Acquires the per-session lock and waits.
    """
    lock = self._locks.setdefault(session_key, asyncio.Lock())
    try:
        async with lock:
            return await self._memory.consolidate(
                session,
                provider,
                model,
                memory_window=self._memory_window,
                enable_contradiction_check=self._enable_contradiction_check,
                archive_all=archive_all,
            )
    finally:
        # Lock is released by async with before finally runs — safe to check.
        entry = self._locks.get(session_key)
        if entry is not None and not entry.locked():
            self._locks.pop(session_key, None)

async def _run(
    self,
    session_key: str,
    session: Session,
    provider: ChatProvider,
    model: str,
) -> None:
    assert self._sem is not None
    try:
        async with self._sem:
            lock = self._locks.setdefault(session_key, asyncio.Lock())
            async with lock:
                try:
                    await self._memory.consolidate(
                        session,
                        provider,
                        model,
                        memory_window=self._memory_window,
                        enable_contradiction_check=self._enable_contradiction_check,
                    )
                except Exception:
                    self._archive_fn(list(session.messages))
                    raise
    finally:
        self._in_progress.discard(session_key)
        lock = self._locks.get(session_key)
        if lock is not None and not lock.locked():
            self._locks.pop(session_key, None)
```

### 7.3 Decouple `fallback_archive_snapshot` from `MemoryPersistence`

`ConsolidationOrchestrator.__init__` receives
`archive_fn: Callable[[list[dict[str, Any]]], None]` — a **synchronous** callable that
takes the raw session message list and appends a plain-text summary to the history file.
`AgentLoop._wire_memory()` constructs it as a closure that replicates the existing
`fallback_archive_snapshot` formatting logic. `memory.history_file` is a direct attribute
on `MemoryStore` (line 96 of `store.py`) that delegates to `persistence.history_file`.

```python
def _archive(messages: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for m in messages:
        content = m.get("content")
        if not content:
            continue
        tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
        timestamp = str(m.get("timestamp", "?"))[:16]
        role = str(m.get("role", "unknown")).upper()
        lines.append(f"[{timestamp}] {role}{tools}: {content}")
    if lines:
        header = (
            f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] "
            f"Fallback archive ({len(lines)} messages)"
        )
        self.context.memory.persistence.append_text(
            self.context.memory.history_file,
            header + "\n" + "\n".join(lines) + "\n\n",
        )

self._consolidator = ConsolidationOrchestrator(
    memory=self.context.memory,
    archive_fn=_archive,
    max_concurrent=3,
    memory_window=self.config.memory_window,
    enable_contradiction_check=self.config.memory_enable_contradiction_check,
)
```

`ConsolidationOrchestrator` never imports `MemoryPersistence`.

**`archive_fn` is synchronous.** `MemoryPersistence.append_text` is a synchronous
`@staticmethod` — this matches the existing `fallback_archive_snapshot` behaviour, which
also calls `append_text` synchronously. Keeping it synchronous preserves the pre-existing
pattern; the data written is small (text summary), so the I/O cost is acceptable.

`fallback_archive_snapshot` on the old class is removed. The three sites updated as part
of Step 6 (see Section 9) are:

1. `tests/test_consolidation.py` — the only site that calls `fallback_archive_snapshot`
   directly. Replaced with `archive_fn` spy injection (see Step 6).
2. `AgentLoop._consolidate_memory` (line 945–958 of `loop.py`) — does **not** call
   `fallback_archive_snapshot`; it calls `self._consolidator.consolidate(...)`. Updated
   to call `await self._consolidator.consolidate_and_wait(session.key, session,
   self.provider, self.model, archive_all=archive_all)`. (`session.key` is used because
   `_consolidate_memory` receives a `Session` but not a separate `session_key`.)
3. `MessageProcessor._handle_slash_new` (lines 545–578) currently calls
   `get_lock()` (line 547), `self._consolidating.add()` (line 548), and `prune_lock()`
   (line 571) directly — these three calls must be removed because `get_lock`,
   `prune_lock`, and `_consolidating` are removed from the new API. After cleanup,
   `_handle_slash_new` retains only `await self._consolidate_memory(temp, archive_all=True)`.
   `MessageProcessor._consolidate_memory` (line 709) is updated to distinguish paths:
   `archive_all=True` calls `await self._consolidator.consolidate_and_wait(...)`;
   normal path calls `self._consolidator.submit(...)`.

### 7.4 Simplification — Three sites updated

**`MessageProcessor.__init__`** (lines 93–95): remove `_consolidating: set[str]`,
`_consolidation_tasks: set[asyncio.Task]`, `_consolidation_sem: asyncio.Semaphore`.
`MessageProcessor._consolidate_memory` is updated: for the normal path it calls
`self._consolidator.submit(session.key, session, provider, model)`, and for the
`archive_all=True` path (used by `/new`) it calls
`await self._consolidator.consolidate_and_wait(session.key, session, provider, model,
archive_all=True)`. `MessageProcessor._handle_slash_new` is stripped of its direct
`get_lock`/`_consolidating.add`/`prune_lock` calls (lines 547, 548, 571); it then
delegates purely via `await self._consolidate_memory(temp, archive_all=True)`.

**`AgentLoop._wire_memory()`** (lines 413–416): remove the three consolidation state
fields. The current orchestrator construction `ConsolidationOrchestrator(self.context.memory)`
uses a single positional argument. Replace it with the full named-keyword constructor:
`ConsolidationOrchestrator(memory=self.context.memory, archive_fn=_archive,
max_concurrent=3, memory_window=self.config.memory_window,
enable_contradiction_check=self.config.memory_enable_contradiction_check)`.

**`AgentLoop._consolidate_memory()`** (line 945–958): update to call
`await self._consolidator.consolidate_and_wait(session.key, session, self.provider,
self.model, archive_all=archive_all)`. Use `session.key` — not a separate `session_key`
variable, as `_consolidate_memory` only receives `session`. The `memory_window` and
`enable_contradiction_check` values are constructor-injected into the orchestrator —
do **not** pass them as call-site kwargs.

`AgentLoop.run()` wraps the main while loop with `async with self._consolidator:` so that
pending background tasks drain before `run()` returns. `stop()` is unchanged.

---

## Section 8: Module Boundary Rules

- `profile_io.py` must **never** import from `channels/`, `bus/`, `session/`, or
  `agent/loop`
- `profile_correction.py` must **never** import from `channels/` or `bus/`
- `token_budget.py` must **never** import from any `agent/memory/` module — pure logic only
- `consolidation.py` must **never** import from `channels/` or `agent/loop`
- `ProfileCache` is not exported from `nanobot/agent/memory/__init__.py` — internal detail
  of `ProfileStore`

---

## Section 9: Migration Steps

### Step 1 — Extract `ProfileCache` and `ProfileStore` (no behavior change)

Create `profile_io.py` with `ProfileCache` and `ProfileStore`. `profile.py` now imports
and re-exports `ProfileStore as ProfileManager` for backward compatibility while tests are
migrated. Add `tests/test_profile_store.py`.

### Step 2 — Move conflict-detection helpers to `ConflictManager`

Move `_conflict_pair`, `apply_profile_updates`, `has_open_conflict` into `ConflictManager`
in `conflicts.py`. Update `ProfileStore` to call `self._conflict_mgr.apply_profile_updates`.
No behavior change. Existing `tests/test_agent_loop.py` must pass.

### Step 3 — Create `CorrectionOrchestrator`

Create `profile_correction.py` with `CorrectionOrchestrator`. Move
`apply_live_user_correction` body. `MemoryStore` constructs `CorrectionOrchestrator` and
delegates to `self._corrector.apply_live_user_correction(content, channel=channel,
chat_id=chat_id, enable_contradiction_check=enable_contradiction_check)`.

Update `store.py` to import `ProfileStore` from `profile_io` (not `profile`).
Update `context_assembler.py` line 18: change `from .profile import ProfileManager`
to `from .profile_io import ProfileStore`, and update the `profile_mgr: ProfileManager`
type annotations in `ContextAssembler.__init__` and `ContextAssembler.build()` to use
`ProfileStore`.
Delete `profile.py`. Update `nanobot/agent/memory/__init__.py` to re-export `ProfileStore`
in place of `ProfileManager` (keeping `ProfileManager = ProfileStore` alias for one
release).

### Step 4 — `token_budget.py` and `MemorySectionWeights`

Create `token_budget.py` with `TokenBudgetAllocator`, `SectionBudget`,
`DEFAULT_SECTION_WEIGHTS`. Add `MemorySectionWeights` to `config/schema.py`.
Wire into `MemoryStore` and `ContextAssembler`. Delete `_SECTION_PRIORITY_WEIGHTS` and
`_allocate_section_budgets` from `context_assembler.py`. Add `tests/test_token_budget.py`.

### Step 5 — Graph memoization

Add `_graph_cache` reset to `MemoryRetriever.retrieve()` and update
`_collect_graph_entity_names`. Add cache-hit test to `tests/test_retriever.py`.

### Step 6 — `ConsolidationOrchestrator` rewrite

Rewrite `consolidation.py` with `asyncio.TaskGroup`, `submit()`,
`consolidate_and_wait()`, `_run()`, `archive_fn`, `_in_progress` guard, and injected
`memory_window`/`enable_contradiction_check` params.

Update `AgentLoop._wire_memory()` (lines 413–416): replace the three removed state
fields with `archive_fn` closure construction; pass `memory_window` and
`enable_contradiction_check` from config to the orchestrator constructor.

Update `AgentLoop._consolidate_memory()` (lines 945–958): replace
`self._consolidator.consolidate(...)` with
`self._consolidator.consolidate_and_wait(session.key, session, self.provider, self.model,
archive_all=archive_all)`.

Update `AgentLoop.run()`: wrap the main while loop with `async with self._consolidator:`.

Update `MessageProcessor._consolidate_memory` (line 709): for the background path call
`self._consolidator.submit(session.key, session, provider, model)`; for the
`archive_all=True` path call `await self._consolidator.consolidate_and_wait(session.key,
session, provider, model, archive_all=True)`. Remove `_consolidation_tasks`,
`_consolidation_sem`, and `_consolidating`.

Update `MessageProcessor._handle_slash_new` (lines 545–578): strip the direct
`get_lock()` (line 547), `self._consolidating.add()` (line 548), `async with lock:`,
and `prune_lock()` (line 571) calls — these are removed with the state fields. After
cleanup, `_handle_slash_new` retains only `await self._consolidate_memory(temp,
archive_all=True)` for the archival call, delegating all lock/guard logic into
`_consolidate_memory`.

Rewrite `tests/test_consolidation.py` in full — three classes must be adapted:

- **`TestConsolidationLocks`**: tests `get_lock()`/`prune_lock()` which are removed.
  Replace with tests for `_in_progress` deduplication: call `submit()` twice for the
  same session key and verify the second call is a no-op.
- **`TestConsolidateDelegate`**: tests the old `consolidate()` method which is removed.
  Replace with tests for `submit()` and `consolidate_and_wait()`.
- **`TestFallbackArchive`**: tests `fallback_archive_snapshot()` which is removed.
  Replace with `archive_fn` spy injection: pass a spy callable to the orchestrator
  constructor and assert it is called (with the session's message list) when
  `MemoryStore.consolidate()` raises.

Add `tests/test_consolidation_orchestrator.py`.

### Step 7 — Final validation

Run `make check`. Verify `profile.py` is deleted. Verify `token_budget.py` has zero
imports from `agent/memory/`. Update `docs/architecture.md` with new module boundaries.

---

## Section 10: Test Strategy

| Step | New test file | What it tests |
|------|--------------|---------------|
| 1 | `tests/test_profile_store.py` | `ProfileCache` invalidation, `ProfileStore` read/write/belief CRUD |
| 2 | `tests/test_conflicts.py` (extend) | `apply_profile_updates`, `has_open_conflict`, `_conflict_pair` |
| 3 | `tests/test_profile_correction.py` | `CorrectionOrchestrator.apply_live_user_correction` with mock subsystems |
| 4 | `tests/test_token_budget.py` | `TokenBudgetAllocator.allocate` for all 7 intents; config override merging; unknown intent fallback |
| 5 | `tests/test_retriever.py` (extend) | Graph cache hit within one retrieve(); reset between calls |
| 6 | `tests/test_consolidation_orchestrator.py` | `submit()` + per-session lock exclusion; graceful drain on `__aexit__`; `archive_fn` called on failure |
| 7 | `make check` | Full pipeline: lint + typecheck + import-check + all tests |

Existing `tests/test_agent_loop.py` must pass unchanged throughout.
No test logic modifications — only import paths may change when `ProfileManager` is renamed
to `ProfileStore`.
