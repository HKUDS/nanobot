# Async Memory Read Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the memory retrieval read path from sync-with-asyncio.run()-hack to properly async, eliminating event loop blocking during every agent turn.

**Architecture:** The memory retrieval chain (`build_system_prompt → get_memory_context → ContextAssembler.build → MemoryRetriever.retrieve`) is currently synchronous but contains an async embedding call bridged via `asyncio.run()` (which always fails in production, falling back to a per-turn `ThreadPoolExecutor`). We convert this chain to async top-down: each method becomes `async def`, callers add `await`. DB calls get `asyncio.to_thread()` per `UnifiedMemoryDB`'s documented contract. The CLI path uses `asyncio.run()` at the entry point (the project's established pattern). No logic changes — only async/await propagation.

**Tech Stack:** Python asyncio, pytest-asyncio (auto mode)

**Scope boundary:** This plan covers ONLY the read path. The write path (`append_events`, consolidation DB calls) is a separate concern.

---

### Task 1: Make `MemoryRetriever.retrieve()` and `_retrieve_unified()` async

This is the core fix. The `asyncio.run()` hack and `ThreadPoolExecutor` fallback are deleted. The embedding call becomes a simple `await`. DB calls are wrapped in `asyncio.to_thread()` per `UnifiedMemoryDB`'s documented contract, and the two DB queries run concurrently via `asyncio.gather()`.

**Files:**
- Modify: `nanobot/memory/read/retriever.py:55-165`
- Test: `tests/test_retriever.py`

- [ ] **Step 1: Write the failing test — async `retrieve()` returns results**

In `tests/test_retriever.py`, add a new test class at the end of the file. This test verifies that `retrieve()` works as an async method with `await`:

```python
class TestAsyncRetrieve:
    """Verify retrieve() is properly async."""

    async def test_async_retrieve_returns_results(self, tmp_path: Path) -> None:
        """retrieve() can be awaited and returns results."""
        from nanobot.memory.unified_db import UnifiedMemoryDB
        from nanobot.memory.embedder import HashEmbedder

        db = UnifiedMemoryDB(tmp_path / "mem.db")
        embedder = HashEmbedder(dims=384)

        # Seed one event
        vec = await embedder.embed("dark mode preference")
        db.insert_event(
            {"content": "User prefers dark mode", "event_type": "preference", "id": "e1"},
            embedding=vec,
        )

        scorer = RetrievalScorer(reranker=_make_reranker())
        graph_aug = GraphAugmenter(read_events_fn=lambda **kw: db.read_events(**kw))
        planner = RetrievalPlanner()
        retriever = MemoryRetriever(
            scorer=scorer, graph_aug=graph_aug, planner=planner, db=db, embedder=embedder,
        )

        results = await retriever.retrieve("dark mode", top_k=3)
        assert isinstance(results, list)
        assert len(results) >= 1

    async def test_async_retrieve_no_db_returns_empty(self) -> None:
        """retrieve() returns [] when db is None."""
        scorer = RetrievalScorer(reranker=_make_reranker())
        graph_aug = GraphAugmenter(read_events_fn=lambda **kw: [])
        planner = RetrievalPlanner()
        retriever = MemoryRetriever(
            scorer=scorer, graph_aug=graph_aug, planner=planner,
        )
        results = await retriever.retrieve("anything", top_k=3)
        assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ../nanobot-async-memory-read && python -m pytest tests/test_retriever.py::TestAsyncRetrieve -v`
Expected: FAIL — `retrieve()` is not async, so `await` on it raises `TypeError: object list can't be used in 'await' expression`

- [ ] **Step 3: Convert `retrieve()` and `_retrieve_unified()` to async**

Edit `nanobot/memory/read/retriever.py`. The changes:

1. Add `import asyncio` at the top-level imports (remove the deferred `import asyncio` at line 95).
2. Convert `retrieve()` (line 55) from `def` to `async def`. Add `await` before `self._retrieve_unified(...)`.
3. Convert `_retrieve_unified()` (line 81) from `def` to `async def`.
4. Replace the `asyncio.run()` / `ThreadPoolExecutor` hack (lines 95-114) with:
   ```python
   query_vec = await embedder.embed(query)
   ```
5. Wrap the two DB calls (lines 117-118) with `asyncio.to_thread` and run them concurrently:
   ```python
   vec_results, fts_results = await asyncio.gather(
       asyncio.to_thread(self._db.search_vector, query_vec, candidate_k),
       asyncio.to_thread(self._db.search_fts, query, candidate_k),
   )
   ```
6. Wrap the fallback `read_events` call (line 124) with `asyncio.to_thread`:
   ```python
   candidates = await asyncio.to_thread(self._db.read_events, limit=candidate_k)
   ```

The full `_retrieve_unified` method after changes:

```python
async def _retrieve_unified(
    self,
    query: str,
    *,
    top_k: int,
    recency_half_life_days: float | None,
    t0: float,
) -> list[dict[str, Any]]:
    """Single fused retrieval: vector + FTS5 + RRF.

    Used when ``UnifiedMemoryDB`` and ``Embedder`` are injected.  Runs
    embedding and dual-source search (vector KNN + FTS5), fuses via
    Reciprocal Rank Fusion, then applies the standard scoring pipeline.
    """
    assert self._db is not None  # noqa: S101 — guarded by caller
    assert self._embedder is not None  # noqa: S101

    plan = self._planner.plan(query)
    policy = plan.policy
    candidate_k = max(1, min(top_k * int(policy.get("candidate_multiplier", 3)), 60))

    # 1. Embed query
    query_vec = await self._embedder.embed(query)

    # 2. Dual source — DB is synchronous; offload per UnifiedMemoryDB contract
    vec_results, fts_results = await asyncio.gather(
        asyncio.to_thread(self._db.search_vector, query_vec, candidate_k),
        asyncio.to_thread(self._db.search_fts, query, candidate_k),
    )

    # 3. Fuse via RRF
    candidates = self._fuse_results(vec_results, fts_results, vector_weight=0.7)

    if not candidates:
        candidates = await asyncio.to_thread(self._db.read_events, limit=candidate_k)
        if not candidates:
            bind_trace().debug(
                "Memory retrieve source=unified results=0 duration_ms={:.0f}",
                (time.monotonic() - t0) * 1000,
            )
            return []

    # 4. Enrich metadata
    self._enrich_item_metadata(candidates)

    # 5. Filter
    filtered, _filter_counts = self._scorer.filter_items(candidates, plan)

    # 6. Score
    profile_data = self._scorer.load_profile_scoring_data()
    graph_entities = self._graph_aug.collect_graph_entity_names(
        query, self._graph_aug._read_events_fn()
    )
    scored = self._scorer.score_items(
        filtered,
        plan,
        profile_data,
        graph_entities,
        use_recency=True,
        router_enabled=True,
        type_separation_enabled=True,
    )

    # 7. Rerank
    scored = self._scorer.rerank_items(query, scored)

    # 8. Sort + truncate
    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    results = scored[:top_k]

    bind_trace().debug(
        "Memory retrieve source=unified results={} duration_ms={:.0f}",
        len(results),
        (time.monotonic() - t0) * 1000,
    )
    return results
```

Remove the `import concurrent.futures` that was inside `_retrieve_unified`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ../nanobot-async-memory-read && python -m pytest tests/test_retriever.py::TestAsyncRetrieve -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: PASS (or errors from downstream callers — those are fixed in subsequent tasks)

- [ ] **Step 6: Commit**

```bash
cd ../nanobot-async-memory-read
git add nanobot/memory/read/retriever.py tests/test_retriever.py
git commit -m "refactor(memory): make MemoryRetriever.retrieve() async

Convert retrieve() and _retrieve_unified() from sync to async def.
Delete the asyncio.run() / ThreadPoolExecutor hack that blocked the
event loop on every turn. Embedding is now a simple await. DB queries
use asyncio.to_thread() per UnifiedMemoryDB's documented contract and
run concurrently via asyncio.gather().

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Make `ContextAssembler.build()` async

`ContextAssembler.build()` calls `self._retrieve_fn(...)` which is now async. The method must become async and await the retrieval call. The `retrieve_fn` callback type annotation changes from `Callable[..., list[...]]` to `Callable[..., Awaitable[list[...]]]`.

**Files:**
- Modify: `nanobot/memory/read/context_assembler.py:64-134`
- Modify: `nanobot/memory/store.py:154-165` (lambda wiring)
- Modify: `nanobot/memory/store.py:323-335` (lazy assembler lambda wiring)

- [ ] **Step 1: Write the failing test — async `build()` returns string**

In `tests/test_store_helpers.py`, add a test (or update the existing `test_retrieve_and_memory_context` if it's simpler to verify the async chain there). Actually, since `ContextAssembler.build()` is tested indirectly via `get_memory_context()`, and `get_memory_context()` will also become async in the next task, we test the full chain in Task 3. Here we do the conversion and verify with lint/typecheck.

Skip dedicated test — the chain is verified end-to-end in Task 3.

- [ ] **Step 2: Update `ContextAssembler` constructor type annotation**

In `nanobot/memory/read/context_assembler.py`, change the `retrieve_fn` parameter type at line 67:

From:
```python
retrieve_fn: Callable[..., list[dict[str, Any]]],
```

To:
```python
retrieve_fn: Callable[..., Awaitable[list[dict[str, Any]]]],
```

Add `Awaitable` to the typing imports at the top of the file. The existing import line should look like:

```python
from typing import TYPE_CHECKING, Any, Awaitable, Callable
```

(Check the existing imports first and just add `Awaitable` to what's already there.)

- [ ] **Step 3: Convert `build()` to async and await the retrieve call**

In `nanobot/memory/read/context_assembler.py`, change line 97:

From:
```python
def build(
```

To:
```python
async def build(
```

Change lines 127-133 to await the retrieve call:

From:
```python
        try:
            retrieved = self._retrieve_fn(
                query or "",
                top_k=retrieval_k,
                recency_half_life_days=recency_half_life_days,
                embedding_provider=embedding_provider,
            )
        except Exception:  # crash-barrier: multi-subsystem retrieval pipeline
```

To:
```python
        try:
            retrieved = await self._retrieve_fn(
                query or "",
                top_k=retrieval_k,
                recency_half_life_days=recency_half_life_days,
                embedding_provider=embedding_provider,
            )
        except Exception:  # crash-barrier: multi-subsystem retrieval pipeline
```

- [ ] **Step 4: Update the lambda wiring in `MemoryStore.__init__`**

In `nanobot/memory/store.py`, the lambda at line 156 wraps the now-async `retrieve()`:

From:
```python
retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
```

This lambda already correctly forwards the call. Since `self.retriever.retrieve()` now returns a coroutine, the lambda returns a coroutine, and `await` in `build()` will await it. **No change needed** — the lambda transparently propagates the async return.

Similarly, the lazy assembler at line 325:
```python
retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
```
**No change needed.**

And the `EvalRunner` lambda at line 236:
```python
retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
```
**Note:** `EvalRunner` calls `retrieve_fn` synchronously (line 199 of `nanobot/eval/memory_eval.py`). This will break. We handle this in Task 6.

- [ ] **Step 5: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: May show errors from `get_memory_context` (fixed in Task 3) and `EvalRunner` (fixed in Task 6). The `context_assembler.py` changes themselves should be clean.

- [ ] **Step 6: Commit**

```bash
cd ../nanobot-async-memory-read
git add nanobot/memory/read/context_assembler.py
git commit -m "refactor(memory): make ContextAssembler.build() async

Convert build() to async def. The retrieve_fn callback now returns
an Awaitable and is awaited. Lambda wiring in MemoryStore transparently
propagates the coroutine.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Make `MemoryStore.get_memory_context()` async

The facade method becomes async and awaits `ContextAssembler.build()`.

**Files:**
- Modify: `nanobot/memory/store.py:337-356`

- [ ] **Step 1: Convert `get_memory_context()` to async**

In `nanobot/memory/store.py`, change line 337:

From:
```python
def get_memory_context(
```

To:
```python
async def get_memory_context(
```

Change line 348:

From:
```python
    return self._ensure_assembler().build(
```

To:
```python
    return await self._ensure_assembler().build(
```

- [ ] **Step 2: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: Errors from callers (`build_system_prompt`, tests) — fixed in subsequent tasks.

- [ ] **Step 3: Commit**

```bash
cd ../nanobot-async-memory-read
git add nanobot/memory/store.py
git commit -m "refactor(memory): make MemoryStore.get_memory_context() async

Facade method now awaits ContextAssembler.build(). Callers updated
in subsequent commits.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Make `ContextBuilder.build_system_prompt()` async

The sync island in the context layer. `build_system_prompt()` calls `get_memory_context()` (now async). It becomes async, and its caller `build_messages()` adds `await`.

**Files:**
- Modify: `nanobot/context/context.py:99-172` (`build_system_prompt`)
- Modify: `nanobot/context/context.py:252` (call site in `build_messages`)

- [ ] **Step 1: Convert `build_system_prompt()` to async**

In `nanobot/context/context.py`, change line 99:

From:
```python
def build_system_prompt(
```

To:
```python
async def build_system_prompt(
```

Change line 126 to await the memory call:

From:
```python
                memory = self.memory.get_memory_context(
```

To:
```python
                memory = await self.memory.get_memory_context(
```

- [ ] **Step 2: Update call site in `build_messages()`**

In `nanobot/context/context.py`, change line 252:

From:
```python
        system_prompt = self.build_system_prompt(current_message=current_message)
```

To:
```python
        system_prompt = await self.build_system_prompt(current_message=current_message)
```

- [ ] **Step 3: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: Errors from test files calling `build_system_prompt()` synchronously — fixed in Task 7.

- [ ] **Step 4: Commit**

```bash
cd ../nanobot-async-memory-read
git add nanobot/context/context.py
git commit -m "refactor(context): make build_system_prompt() async

build_system_prompt() now awaits get_memory_context(). The sync
island that blocked the event loop during every agent turn is
eliminated. build_messages() adds await at the call site.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Make `AnswerVerifier` methods async

`should_force_verification()` and `_estimate_grounding_confidence()` call `retrieve()` (now async). Both become async. The call site in `message_processor.py` adds `await`.

**Files:**
- Modify: `nanobot/agent/verifier.py:183-232`
- Modify: `nanobot/agent/message_processor.py:285`
- Test: `tests/test_verifier.py`

- [ ] **Step 1: Write the failing test — async `should_force_verification`**

In `tests/test_verifier.py`, update the existing tests. The test functions that call `_estimate_grounding_confidence()` and `should_force_verification()` must become `async def` and add `await`. First, verify the existing tests call these methods. Then update them.

The existing tests at lines ~102-130 call `v._estimate_grounding_confidence("anything")` and `v.should_force_verification(...)` synchronously. They need to become:

```python
async def test_no_memory_returns_zero(self) -> None:
    v = AnswerVerifier(provider=mock_provider, config=_cfg())
    assert await v._estimate_grounding_confidence("anything") == 0.0

async def test_empty_results_returns_zero(self) -> None:
    ...
    assert await v._estimate_grounding_confidence("anything") == 0.0

async def test_score_clamped_to_unit_interval(self) -> None:
    ...
    assert await v._estimate_grounding_confidence("anything") == 1.0

async def test_memory_exception_returns_zero(self) -> None:
    ...
    assert await v._estimate_grounding_confidence("anything") == 0.0

async def test_normal_score_returned(self) -> None:
    ...
    assert await v._estimate_grounding_confidence("anything") == 1.0
```

Note: The mock `retrieve` method on the mock memory object must also become async. If the existing tests mock `retriever.retrieve` as a sync method, update the mock to return a coroutine. The simplest approach: use `AsyncMock` instead of `MagicMock` for the `retrieve` method, or wrap the return value in a coroutine.

**Important:** Read the existing test file first to understand the mock setup before editing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ../nanobot-async-memory-read && python -m pytest tests/test_verifier.py -v -k "grounding or force_verification"`
Expected: FAIL — the methods are not yet async

- [ ] **Step 3: Convert verifier methods to async**

In `nanobot/agent/verifier.py`:

Change line 183:
```python
async def should_force_verification(self, text: str) -> bool:
```

Change line 187 to await:
```python
    confidence = await self._estimate_grounding_confidence(text)
```

Change line 218:
```python
async def _estimate_grounding_confidence(self, query: str) -> float:
```

Change line 222 to await:
```python
        items = await self._memory.retriever.retrieve(query, top_k=1)
```

- [ ] **Step 4: Update call site in `message_processor.py`**

In `nanobot/agent/message_processor.py`, change line 285:

From:
```python
            verify_before_answer = self.verifier.should_force_verification(msg.content)
```

To:
```python
            verify_before_answer = await self.verifier.should_force_verification(msg.content)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ../nanobot-async-memory-read && python -m pytest tests/test_verifier.py -v`
Expected: PASS

- [ ] **Step 6: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: PASS (or errors from remaining test files — fixed in Task 7)

- [ ] **Step 7: Commit**

```bash
cd ../nanobot-async-memory-read
git add nanobot/agent/verifier.py nanobot/agent/message_processor.py tests/test_verifier.py
git commit -m "refactor(agent): make AnswerVerifier grounding check async

should_force_verification() and _estimate_grounding_confidence() now
await retrieve(). The call site in message_processor adds await,
eliminating the second event loop block per turn.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Fix `EvalRunner` and CLI callers

`EvalRunner` calls `retrieve_fn` synchronously. The CLI (`cli/memory.py`) and eval script (`scripts/eval_agent_questions.py`) call `retrieve()` and `get_memory_context()` synchronously. These are sync entry points with no running event loop, so they use `asyncio.run()` at the call site — the project's established pattern for CLI commands.

**Files:**
- Modify: `nanobot/eval/memory_eval.py` (~line 199)
- Modify: `nanobot/cli/memory.py:57`
- Modify: `scripts/eval_agent_questions.py:97,101`

- [ ] **Step 1: Fix `EvalRunner` — make the retrieve call async**

Read `nanobot/eval/memory_eval.py` to understand the full context around line 199. The method that calls `self._retrieve(...)` must become `async def`, and the call must be `await`ed. Trace upward: if the calling method is already async, just add `await`. If it's sync, convert it to async and update its callers within the same file.

The `retrieve_fn` type annotation at line 30 must change:

From:
```python
retrieve_fn: Callable[..., list[dict[str, Any]]],
```

To:
```python
retrieve_fn: Callable[..., Awaitable[list[dict[str, Any]]]],
```

Add `Awaitable` to the typing imports.

- [ ] **Step 2: Fix `cli/memory.py` — wrap async calls with `asyncio.run()`**

In `nanobot/cli/memory.py`, the call at line 57:

From:
```python
        retrieved = store.retriever.retrieve(
            query,
            top_k=top_k,
        )
```

To:
```python
        retrieved = asyncio.run(store.retriever.retrieve(
            query,
            top_k=top_k,
        ))
```

Add `import asyncio` at the top of the file if not already present.

Similarly, search for any `store.get_memory_context(...)` calls in this file and wrap them with `asyncio.run()`.

- [ ] **Step 3: Fix `scripts/eval_agent_questions.py`**

At line 97:
From:
```python
        retrieved = store.retriever.retrieve(query, top_k=6)
```

To:
```python
        retrieved = asyncio.run(store.retriever.retrieve(query, top_k=6))
```

At line 101:
From:
```python
        context = store.get_memory_context(
```

To:
```python
        context = asyncio.run(store.get_memory_context(
```

(Close the `asyncio.run(` parenthesis after the keyword arguments.)

Add `import asyncio` at the top of the file if not already present.

- [ ] **Step 4: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: PASS (or errors from test files only — fixed in Task 7)

- [ ] **Step 5: Commit**

```bash
cd ../nanobot-async-memory-read
git add nanobot/eval/memory_eval.py nanobot/cli/memory.py scripts/eval_agent_questions.py
git commit -m "refactor: adapt CLI and eval callers to async memory API

CLI and eval scripts use asyncio.run() at the entry point — the
project's established pattern for sync-to-async bridges. EvalRunner's
retrieve_fn type updated to Awaitable.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Update test files for async signatures

All test files that call `build_system_prompt()`, `get_memory_context()`, `retrieve()`, or `should_force_verification()` must be updated. Tests that call these in sync context either:
- Become `async def test_*` and add `await` (if the method is used directly), or
- Wrap with `asyncio.run()` (if the test is deliberately sync and calling a thin wrapper)

Since pytest-asyncio is in auto mode, converting `def test_*` to `async def test_*` is mechanical and tests run correctly.

**Important guidance:** For tests that mock `retrieve()` or `get_memory_context()`, the mock must return a coroutine. Use `AsyncMock` (from `unittest.mock`) instead of `MagicMock` for async methods, or set `mock.retrieve = AsyncMock(return_value=[...])`.

**Files (grouped by test file):**

**Group A — `build_system_prompt()` callers (16 call sites across 4 files):**
- Modify: `tests/test_capability_availability.py` (lines 218, 228, 235, 248)
- Modify: `tests/test_context_prompt_cache.py` (lines 34, 37)
- Modify: `tests/test_context_builder.py` (lines 83, 108-110)
- Modify: `tests/test_email_validation.py` (lines 278, 291, 302)

Note: `tests/test_pass2_smoke.py` (lines 163, 176, 180, 456) calls `loop.context.build_system_prompt()` — these also need updating.

**Group B — `get_memory_context()` callers (23 call sites across 10 files):**
- Modify: `tests/contract/test_memory_contracts.py` (lines 454, 479)
- Modify: `tests/integration/test_consolidation_pipeline.py` (lines 88, 109)
- Modify: `tests/integration/test_memory_retrieval_pipeline.py` (lines 280, 293, 298, 309)
- Modify: `tests/test_memory_hybrid.py` (line 336)
- Modify: `tests/test_memory_roundtrip.py` (lines 113, 136, 168, 213, 257)
- Modify: `tests/test_memory_metadata_policy.py` (lines 89, 120, 142, 396)
- Modify: `tests/test_store_branches.py` (lines 253, 484)
- Modify: `tests/test_store_helpers.py` (line 242)
- Modify: `tests/test_token_reduction.py` (lines 38, 103, 120)

**Group C — `retrieve()` callers (37 call sites across 10 files):**
- Modify: `tests/contract/test_memory_contracts.py` (lines 106, 112, 133, 195, 212, 261, 291, 320, 350, 406)
- Modify: `tests/integration/test_agent_memory_write.py` (line 39)
- Modify: `tests/integration/test_memory_retrieval_pipeline.py` (lines 175, 183, 191, 199, 207, 225, 234, 239, 263)
- Modify: `tests/test_extraction_e2e.py` (lines 48, 67)
- Modify: `tests/test_memory_hybrid.py` (lines 123, 622, 681, 747, 789, 829)
- Modify: `tests/test_retriever.py` (lines 118, 636, 646, 654, 734)
- Modify: `tests/test_store_helpers.py` (line 239)
- Modify: `tests/test_workflow_e2e.py` (line 252)

**Group D — `should_force_verification()` / `_estimate_grounding_confidence()` callers:**
- Modify: `tests/test_loop_helper_paths.py` (lines 158, 162, 166)
- Modify: `tests/test_message_processor.py` (line 162 — mock setup)

- [ ] **Step 1: Update Group A — `build_system_prompt()` test callers**

For each test file in Group A:
1. Read the file to understand the test setup and existing mock patterns.
2. Convert `def test_*` functions that call `build_system_prompt()` to `async def test_*`.
3. Add `await` before each `builder.build_system_prompt()` call.
4. If the `ContextBuilder` has a mock memory whose `get_memory_context` is being called, ensure the mock uses `AsyncMock` for that method.

Example transformation (from `test_context_builder.py`):

From:
```python
def test_build_system_prompt_memory_failure_fallback(...):
    ...
    prompt = builder.build_system_prompt(current_message="hello")
```

To:
```python
async def test_build_system_prompt_memory_failure_fallback(...):
    ...
    prompt = await builder.build_system_prompt(current_message="hello")
```

If `memory.get_memory_context` is mocked via `MagicMock(side_effect=...)` or `MagicMock(return_value=...)`, change to `AsyncMock(side_effect=...)` or `AsyncMock(return_value=...)`.

- [ ] **Step 2: Update Group B — `get_memory_context()` test callers**

For each test file in Group B:
1. Read the file.
2. Convert test functions to `async def`.
3. Add `await` before each `store.get_memory_context(...)` call.
4. Check that the `MemoryStore` used in the test has a real `ContextAssembler` (not mocked). If it's a real `MemoryStore` with `HashEmbedder`, the async chain works naturally.

- [ ] **Step 3: Update Group C — `retrieve()` test callers**

For each test file in Group C:
1. Read the file.
2. Convert test functions to `async def`.
3. Add `await` before each `.retrieve(...)` call.
4. If `retrieve` is mocked, use `AsyncMock`.

- [ ] **Step 4: Update Group D — verifier test callers**

For `tests/test_loop_helper_paths.py`:
1. Convert the test function to `async def`.
2. Add `await` before `v._estimate_grounding_confidence(...)` and `v.should_force_verification(...)`.
3. If `retrieve` is mocked on a mock memory object, use `AsyncMock`.

For `tests/test_message_processor.py`:
1. The test at line 162 mocks `should_force_verification`. Since the method is now async, the mock must be `AsyncMock(return_value=True)`.

- [ ] **Step 5: Run full test suite**

Run: `cd ../nanobot-async-memory-read && make test`
Expected: All tests PASS

- [ ] **Step 6: Run lint and typecheck**

Run: `cd ../nanobot-async-memory-read && make lint && make typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd ../nanobot-async-memory-read
git add tests/
git commit -m "test: update test suite for async memory read path

Convert test functions to async def and add await for retrieve(),
get_memory_context(), build_system_prompt(), and
should_force_verification(). Mocks use AsyncMock where needed.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Full validation and cleanup

Run the complete validation suite to catch any missed call sites.

**Files:**
- No new files — validation only

- [ ] **Step 1: Run `make check` (full validation)**

Run: `cd ../nanobot-async-memory-read && make check`

This runs: lint + typecheck + import-check + structure-check + prompt-check + test + integration.

Expected: All green. If any failures:
- **Import boundary violations**: `make import-check` — should be clean (no new cross-boundary imports added)
- **Structure violations**: `make structure-check` — should be clean (no new files, no LOC changes)
- **Type errors**: Fix any missed `await` or `AsyncMock` updates
- **Test failures**: Fix any missed async conversions

- [ ] **Step 2: Verify no `asyncio.run()` remains in retriever.py**

Run: `cd ../nanobot-async-memory-read && grep -n "asyncio.run\|concurrent.futures\|ThreadPoolExecutor" nanobot/memory/read/retriever.py`
Expected: No output (all removed)

- [ ] **Step 3: Verify no `asyncio.run()` in non-entry-point code**

Run: `cd ../nanobot-async-memory-read && grep -rn "asyncio.run(" nanobot/ --include="*.py" | grep -v "cli/" | grep -v "# entry-point"`
Expected: No output (only CLI files should have `asyncio.run()`)

Note: `scripts/eval_agent_questions.py` is outside `nanobot/` so it won't appear. If other files in `nanobot/` show up, investigate — they may be legitimate entry points or may need fixing.

- [ ] **Step 4: Run integration tests specifically**

Run: `cd ../nanobot-async-memory-read && make test-integration`
Expected: PASS (integration tests exercise the full retrieval pipeline)

- [ ] **Step 5: Commit if any fixes were needed**

If Step 1 revealed issues that required fixes:
```bash
cd ../nanobot-async-memory-read
git add -A
git commit -m "fix: address remaining async conversion issues from make check

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Final commit log review**

Run: `cd ../nanobot-async-memory-read && git log --oneline main..HEAD`
Expected: 6-7 commits, all with conventional commit format, telling a clear story:
1. Core retriever async conversion
2. ContextAssembler.build() async
3. MemoryStore.get_memory_context() async
4. ContextBuilder.build_system_prompt() async
5. AnswerVerifier async
6. CLI/eval callers adapted
7. Test suite updated
8. (Optional) Fixup from make check
