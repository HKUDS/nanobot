# Memory Evaluation Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile `memory-eval` CI benchmark with behavioral contract tests (no LLM), real-LLM round-trip tests, and non-gating observability monitoring.

**Architecture:** Layer 1 (contract tests) expands the existing `tests/contract/test_memory_contracts.py` with 9 invariant tests that verify the retrieval/storage engine without LLM. Layer 2 (round-trip tests) creates `tests/test_memory_roundtrip.py` with 5 scenarios that use real LLM calls to test the full memory lifecycle. Layer 3 converts the existing benchmark to non-gating observability.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio, litellm (for LLM calls), ruff, mypy

**Worktree:** `/home/carlos/nanobot-memory-eval-redesign` (branch `refactor/memory-eval-redesign`)

**Spec:** `docs/superpowers/specs/2026-03-22-memory-eval-redesign.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `tests/contract/test_memory_contracts.py` | Add 9 behavioral invariant tests |
| Create | `tests/test_memory_roundtrip.py` | 5 LLM round-trip scenarios |
| Modify | `pyproject.toml` | Register `llm` pytest marker |
| Rename | `scripts/memory_eval_ci.py` → `scripts/memory_eval_trend.py` | Advisory trend monitoring |
| Delete | `case/memory_eval_baseline.json` | No more threshold gating |
| Modify | `Makefile` | Update `memory-eval` target (advisory, renamed script) |
| Modify | `.github/workflows/memory-eval-trend.yml` | Non-blocking, update path refs |
| Modify | `.github/workflows/ci.yml` | Add LLM round-trip job (optional, skipped without key) |

---

### Task 1: Expand contract tests — behavioral invariants

**Files:**
- Modify: `tests/contract/test_memory_contracts.py`

The existing file has 4 test classes (13 tests). Add a new class `TestBehavioralInvariants` with 9 tests.

- [ ] **Step 1: Read the existing contract test file**

Read `tests/contract/test_memory_contracts.py` to understand the `_make_store` helper and `_sample_events` pattern.

- [ ] **Step 2: Add supersession ordering test**

```python
class TestBehavioralInvariants:
    """Behavioral invariants that must hold regardless of scoring implementation."""

    def test_supersession_ordering(self, tmp_path: Path) -> None:
        """Superseded event must rank below its active replacement."""
        store = _make_store(tmp_path)
        store.ingester.append_events([
            {
                "id": "evt-old-region",
                "type": "fact",
                "summary": "Deployment region is eu-west-1.",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "source": "test",
                "status": "superseded",
                "metadata": {"memory_type": "semantic", "stability": "high"},
            },
            {
                "id": "evt-new-region",
                "type": "fact",
                "summary": "Deployment region is us-east-1.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
                "status": "active",
                "metadata": {"memory_type": "semantic", "stability": "high"},
            },
        ])
        results = store.retriever.retrieve("deployment region", top_k=5)
        summaries = [r.get("summary", "") for r in results]
        active_idx = next(
            (i for i, s in enumerate(summaries) if "us-east-1" in s), None
        )
        superseded_idx = next(
            (i for i, s in enumerate(summaries) if "eu-west-1" in s), None
        )
        assert active_idx is not None, "Active region event not retrieved"
        if superseded_idx is not None:
            assert active_idx < superseded_idx, (
                f"Active (idx={active_idx}) should rank above superseded (idx={superseded_idx})"
            )
```

- [ ] **Step 3: Add recency ordering test**

```python
    def test_recency_ordering(self, tmp_path: Path) -> None:
        """Newer event must rank above older event for the same topic."""
        store = _make_store(tmp_path)
        store.ingester.append_events([
            {
                "id": "evt-old-sprint",
                "type": "task",
                "summary": "Sprint goal: launch v2 dashboard.",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "source": "test",
                "metadata": {"memory_type": "episodic"},
            },
            {
                "id": "evt-new-sprint",
                "type": "task",
                "summary": "Sprint goal: fix authentication bug.",
                "timestamp": "2026-03-15T10:00:00+00:00",
                "source": "test",
                "metadata": {"memory_type": "episodic"},
            },
        ])
        results = store.retriever.retrieve("sprint goal", top_k=5)
        summaries = [r.get("summary", "") for r in results]
        new_idx = next((i for i, s in enumerate(summaries) if "auth" in s.lower()), None)
        old_idx = next((i for i, s in enumerate(summaries) if "v2" in s.lower()), None)
        assert new_idx is not None, "Newer sprint event not retrieved"
        if old_idx is not None:
            assert new_idx < old_idx, "Newer event should rank above older"
```

- [ ] **Step 4: Add negative query test**

```python
    def test_negative_query_no_false_matches(self, tmp_path: Path) -> None:
        """An irrelevant query should not return matching events."""
        store = _make_store(tmp_path)
        store.ingester.append_events([
            {
                "id": "evt-python",
                "type": "fact",
                "summary": "User's primary language is Python.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            },
        ])
        results = store.retriever.retrieve("favorite color blue", top_k=5)
        summaries = " ".join(r.get("summary", "").lower() for r in results)
        assert "color" not in summaries and "blue" not in summaries
```

- [ ] **Step 5: Add high-salience surfacing test**

```python
    def test_high_salience_surfaces_in_top_3(self, tmp_path: Path) -> None:
        """A high-salience event must appear in top 3 for a keyword match."""
        store = _make_store(tmp_path)
        filler = [
            {
                "id": f"evt-filler-{i}",
                "type": "fact",
                "summary": f"Routine fact number {i} about testing infrastructure.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
                "salience": 0.3,
            }
            for i in range(10)
        ]
        critical = {
            "id": "evt-critical",
            "type": "task",
            "summary": "Critical production database outage detected.",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "source": "test",
            "salience": 0.95,
        }
        store.ingester.append_events(filler + [critical])
        results = store.retriever.retrieve("production database outage", top_k=5)
        top_3_summaries = " ".join(
            r.get("summary", "").lower() for r in results[:3]
        )
        assert "outage" in top_3_summaries
```

- [ ] **Step 6: Add dedup idempotency test**

```python
    def test_dedup_idempotency(self, tmp_path: Path) -> None:
        """Appending the same event twice must not create duplicates."""
        store = _make_store(tmp_path)
        event = {
            "id": "evt-dedup",
            "type": "fact",
            "summary": "User works at Globex Corporation.",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "source": "test",
        }
        store.ingester.append_events([event])
        store.ingester.append_events([event])
        events = store.ingester.read_events()
        globex_events = [e for e in events if "Globex" in e.get("summary", "")]
        assert len(globex_events) == 1, f"Expected 1 event, got {len(globex_events)}"
```

- [ ] **Step 7: Add type-appropriate retrieval test**

```python
    def test_type_appropriate_retrieval(self, tmp_path: Path) -> None:
        """Task query should return episodic events above semantic ones."""
        store = _make_store(tmp_path)
        store.ingester.append_events([
            {
                "id": "evt-task",
                "type": "task",
                "summary": "Fix authentication bug in login flow.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
                "metadata": {"memory_type": "episodic", "topic": "task_progress"},
            },
            {
                "id": "evt-fact",
                "type": "fact",
                "summary": "Authentication uses OAuth2 protocol.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
                "metadata": {"memory_type": "semantic", "topic": "knowledge"},
            },
        ])
        results = store.retriever.retrieve("authentication task progress", top_k=5)
        if len(results) >= 2:
            types = [r.get("metadata", {}).get("memory_type", "") for r in results]
            if "episodic" in types and "semantic" in types:
                ep_idx = types.index("episodic")
                sem_idx = types.index("semantic")
                assert ep_idx < sem_idx, "Episodic task should rank above semantic fact"
```

- [ ] **Step 8: Add context assembly completeness test**

```python
    async def test_context_assembly_completeness(self, tmp_path: Path) -> None:
        """get_memory_context must return non-empty string with profile + events."""
        store = _make_store(tmp_path)
        store.profile_mgr.write_profile({
            "preferences": ["Prefers dark mode"],
            "stable_facts": ["Works at Acme Corp"],
            "active_projects": [],
        })
        store.ingester.append_events([
            {
                "id": "evt-ctx",
                "type": "fact",
                "summary": "Primary programming language is Python.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            },
        ])
        context = store.get_memory_context(
            query="Tell me about the user",
            retrieval_k=5,
            token_budget=2000,
        )
        assert isinstance(context, str)
        assert len(context) > 0
        lower = context.lower()
        assert "dark mode" in lower or "acme" in lower, (
            "Context should include profile data"
        )
```

- [ ] **Step 9: Add pinned item inclusion test**

```python
    def test_pinned_item_always_included(self, tmp_path: Path) -> None:
        """A pinned profile item must appear in context regardless of query."""
        store = _make_store(tmp_path)
        profile = {
            "preferences": ["Always use bullet points"],
            "stable_facts": [],
            "active_projects": [],
            "meta": {
                "preferences": {
                    "always use bullet points": {
                        "pinned": True,
                        "status": "active",
                        "last_seen_at": "2026-03-01T12:00:00+00:00",
                    }
                }
            },
        }
        store.profile_mgr.write_profile(profile)
        context = store.get_memory_context(
            query="completely unrelated topic about databases",
            retrieval_k=5,
            token_budget=2000,
        )
        assert "bullet" in context.lower(), "Pinned item must appear in context"
```

- [ ] **Step 10: Run tests and lint**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && make lint && make typecheck && pytest tests/contract/test_memory_contracts.py -v
```

- [ ] **Step 11: Commit**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git add tests/contract/test_memory_contracts.py && git commit -m "test(memory): add 9 behavioral invariant contract tests"
```

---

### Task 2: Create LLM round-trip tests

**Files:**
- Create: `tests/test_memory_roundtrip.py`
- Modify: `pyproject.toml` (add `llm` marker)

- [ ] **Step 1: Register the `llm` pytest marker**

In `pyproject.toml`, find the `markers` list under `[tool.pytest.ini_options]` and add:

```toml
markers = [
    "golden: golden regression tests (frozen behavior baselines)",
    "contract: contract tests for core abstractions",
    "llm: tests requiring a real LLM API key (skipped when unavailable)",
]
```

- [ ] **Step 2: Create the round-trip test file with fixtures**

```python
"""End-to-end memory round-trip tests with real LLM calls.

These tests verify the full memory lifecycle:
  User says X → consolidate() extracts it → get_memory_context() surfaces it

Requires OPENAI_API_KEY (or equivalent) to be set. Skipped otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from nanobot.memory import MemoryStore

pytestmark = pytest.mark.llm

# Skip entire module if no LLM API key is available
_HAS_API_KEY = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY"))
if not _HAS_API_KEY:
    pytest.skip("No LLM API key available — skipping round-trip tests", allow_module_level=True)


def _make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path, embedding_provider="hash")


def _make_provider():
    """Create a real LiteLLM provider for round-trip tests."""
    from nanobot.providers.litellm_provider import LiteLLMProvider
    return LiteLLMProvider()


def _make_session(messages: list[dict[str, Any]]) -> Any:
    """Create a minimal session-like object for consolidation."""
    class _Session:
        def __init__(self, msgs: list[dict[str, Any]]) -> None:
            self.messages = msgs
            self.last_consolidated = 0
            self.key = "test-session"
    return _Session(messages)
```

- [ ] **Step 3: Add preference consolidation round-trip test**

```python
class TestMemoryRoundTrip:
    async def test_preference_consolidation(self, tmp_path: Path) -> None:
        """User states preference → consolidate → preference appears in context."""
        store = _make_store(tmp_path)
        provider = _make_provider()
        session = _make_session([
            {"role": "user", "content": "I always want responses in bullet points, never long paragraphs", "timestamp": "2026-03-01T12:00:00+00:00"},
            {"role": "assistant", "content": "Understood! I'll use bullet points from now on.", "timestamp": "2026-03-01T12:00:30+00:00"},
        ])

        result = await store.consolidate(
            session=session,
            provider=provider,
            model="gpt-4o-mini",
            archive_all=True,
            memory_window=50,
        )
        assert result is True, "Consolidation should succeed"

        context = store.get_memory_context(
            query="How should I format responses for this user?",
            retrieval_k=5,
            token_budget=2000,
        )
        lower = context.lower()
        assert "bullet" in lower, (
            f"Expected 'bullet' in memory context after consolidation. Got: {context[:500]}"
        )
```

- [ ] **Step 4: Add fact storage round-trip test**

```python
    async def test_fact_storage(self, tmp_path: Path) -> None:
        """User states a fact → consolidate → fact retrievable."""
        store = _make_store(tmp_path)
        provider = _make_provider()
        session = _make_session([
            {"role": "user", "content": "I work at Globex Corporation as a senior engineer", "timestamp": "2026-03-01T12:00:00+00:00"},
            {"role": "assistant", "content": "Got it, you're a senior engineer at Globex.", "timestamp": "2026-03-01T12:00:30+00:00"},
        ])

        await store.consolidate(
            session=session,
            provider=provider,
            model="gpt-4o-mini",
            archive_all=True,
            memory_window=50,
        )

        context = store.get_memory_context(
            query="Where does the user work?",
            retrieval_k=5,
            token_budget=2000,
        )
        lower = context.lower()
        assert "globex" in lower, (
            f"Expected 'globex' in memory context. Got: {context[:500]}"
        )
```

- [ ] **Step 5: Add multi-turn accumulation test**

```python
    async def test_multi_turn_accumulation(self, tmp_path: Path) -> None:
        """Multiple turns consolidated → all facts retrievable."""
        store = _make_store(tmp_path)
        provider = _make_provider()

        conversations = [
            [
                {"role": "user", "content": "I prefer dark mode in all my editors", "timestamp": "2026-03-01T10:00:00+00:00"},
                {"role": "assistant", "content": "Noted, dark mode preference.", "timestamp": "2026-03-01T10:00:30+00:00"},
            ],
            [
                {"role": "user", "content": "My main project is called Phoenix and it's a web app", "timestamp": "2026-03-01T11:00:00+00:00"},
                {"role": "assistant", "content": "Got it, Phoenix web app.", "timestamp": "2026-03-01T11:00:30+00:00"},
            ],
            [
                {"role": "user", "content": "The deadline for Phoenix is April 15th", "timestamp": "2026-03-01T12:00:00+00:00"},
                {"role": "assistant", "content": "Noted, April 15 deadline.", "timestamp": "2026-03-01T12:00:30+00:00"},
            ],
        ]

        for msgs in conversations:
            session = _make_session(msgs)
            await store.consolidate(
                session=session,
                provider=provider,
                model="gpt-4o-mini",
                archive_all=True,
                memory_window=50,
            )

        context = store.get_memory_context(
            query="Tell me everything about the user and their projects",
            retrieval_k=10,
            token_budget=3000,
        )
        lower = context.lower()
        # At least 2 of the 3 facts should survive the full pipeline
        hits = sum([
            "dark mode" in lower,
            "phoenix" in lower,
            "april" in lower or "deadline" in lower,
        ])
        assert hits >= 2, (
            f"Expected at least 2 of 3 facts in context (got {hits}). Context: {context[:500]}"
        )
```

- [ ] **Step 6: Add context assembly completeness test**

```python
    async def test_context_assembly_after_consolidation(self, tmp_path: Path) -> None:
        """After consolidation, context includes profile and event data."""
        store = _make_store(tmp_path)
        provider = _make_provider()

        # Seed a profile
        store.profile_mgr.write_profile({
            "preferences": ["Uses vim keybindings"],
            "stable_facts": ["Based in London"],
            "active_projects": [],
        })

        session = _make_session([
            {"role": "user", "content": "I just started using Rust for a side project", "timestamp": "2026-03-01T12:00:00+00:00"},
            {"role": "assistant", "content": "Exciting! Rust is great for systems programming.", "timestamp": "2026-03-01T12:00:30+00:00"},
        ])

        await store.consolidate(
            session=session,
            provider=provider,
            model="gpt-4o-mini",
            archive_all=True,
            memory_window=50,
        )

        context = store.get_memory_context(
            query="What do I know about this user?",
            retrieval_k=10,
            token_budget=3000,
        )
        assert len(context) > 100, "Context should be substantial"
        lower = context.lower()
        # Profile data should surface
        assert "vim" in lower or "london" in lower, (
            "Profile data should appear in context"
        )
```

- [ ] **Step 7: Add fact correction round-trip test**

```python
    async def test_fact_correction(self, tmp_path: Path) -> None:
        """Old fact seeded, user corrects → new fact surfaces in context."""
        store = _make_store(tmp_path)
        provider = _make_provider()

        # Seed old fact
        store.ingester.append_events([{
            "id": "evt-old-company",
            "type": "fact",
            "summary": "User works at Acme Corp.",
            "timestamp": "2026-02-01T12:00:00+00:00",
            "source": "test",
        }])

        # User corrects
        session = _make_session([
            {"role": "user", "content": "Actually I left Acme, I'm working at Globex now", "timestamp": "2026-03-15T12:00:00+00:00"},
            {"role": "assistant", "content": "Updated — you're now at Globex.", "timestamp": "2026-03-15T12:00:30+00:00"},
        ])

        await store.consolidate(
            session=session,
            provider=provider,
            model="gpt-4o-mini",
            archive_all=True,
            memory_window=50,
        )

        context = store.get_memory_context(
            query="Where does the user work?",
            retrieval_k=5,
            token_budget=2000,
        )
        lower = context.lower()
        assert "globex" in lower, (
            f"New employer 'globex' should appear in context. Got: {context[:500]}"
        )
```

- [ ] **Step 8: Run tests locally (requires API key)**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && pytest tests/test_memory_roundtrip.py -v -m llm
```

If no API key: tests will be skipped, not failed.

- [ ] **Step 9: Run contract tests + lint**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && make lint && make typecheck && pytest tests/contract/test_memory_contracts.py tests/test_memory_roundtrip.py -v
```

- [ ] **Step 10: Commit**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git add tests/test_memory_roundtrip.py pyproject.toml && git commit -m "test(memory): add LLM round-trip tests for full memory lifecycle"
```

---

### Task 3: Make memory-eval non-blocking + rename script

**Files:**
- Rename: `scripts/memory_eval_ci.py` → `scripts/memory_eval_trend.py`
- Delete: `case/memory_eval_baseline.json`
- Modify: `Makefile`

- [ ] **Step 1: Rename the eval script**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git mv scripts/memory_eval_ci.py scripts/memory_eval_trend.py
```

- [ ] **Step 2: Remove `--strict` from the script**

Read `scripts/memory_eval_trend.py` and find the `--strict` argument handling. Either remove the flag entirely or change the default to `False`. The script should always exit 0 (advisory).

- [ ] **Step 3: Delete baseline file**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git rm case/memory_eval_baseline.json
```

- [ ] **Step 4: Update Makefile**

Replace the `memory-eval` target to use the renamed script and drop `--strict` and `--baseline-file`:

```makefile
memory-eval:
	$(PYTHON) scripts/memory_eval_trend.py \
		--workspace /tmp/memory_eval_workspace \
		--cases-file case/memory_eval_cases.json \
		--seed-events case/memory_seed_events.jsonl \
		--seed-profile case/memory_seed_profile.json \
		--output-file artifacts/memory_eval_latest.json \
		--history-file artifacts/memory_eval_history.json \
		--summary-file artifacts/memory_eval_summary.md
```

- [ ] **Step 5: Run lint and verify Makefile works**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && make lint && make memory-eval
```
Expected: runs without error, prints results, exits 0.

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git add -A && git commit -m "refactor(eval): rename memory_eval_ci to trend, remove CI gating"
```

---

### Task 4: Update CI workflows

**Files:**
- Modify: `.github/workflows/memory-eval-trend.yml`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Update memory-eval-trend workflow**

Make non-blocking:
- Remove `--strict` from the script invocation
- Remove `--baseline-file` argument
- Update path trigger: `scripts/memory_eval_ci.py` → `scripts/memory_eval_trend.py`
- Remove `case/memory_eval_baseline.json` from path triggers
- Add `continue-on-error: true` to the run step (advisory)

- [ ] **Step 2: Add LLM round-trip job to ci.yml**

Add a new job after the `test` matrix:

```yaml
  llm-roundtrip:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    if: github.event_name == 'push' || (github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository)
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run LLM round-trip tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          if [ -z "$OPENAI_API_KEY" ]; then
            echo "No API key — skipping LLM tests"
            exit 0
          fi
          pytest tests/test_memory_roundtrip.py -v -m llm --timeout=120
```

Note: `if:` condition ensures this only runs on internal PRs (not forks, which don't have secrets).

- [ ] **Step 3: Run lint on workflow files**

Verify YAML syntax is valid.

- [ ] **Step 4: Commit**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git add .github/workflows/ && git commit -m "ci: add LLM round-trip job, make memory-eval trend non-blocking"
```

---

### Task 5: Update documentation

**Files:**
- Modify: `CLAUDE.md` (if memory-eval is mentioned)
- Modify: `docs/test-strategy.md` (if it exists)

- [ ] **Step 1: Check what docs reference memory-eval**

```bash
grep -rn "memory-eval\|memory_eval" CLAUDE.md docs/ --include="*.md"
```

- [ ] **Step 2: Update references**

Replace references to `make memory-eval` as a CI gate with:
- `make memory-eval` is now advisory (trend monitoring)
- Memory quality is tested by contract tests + LLM round-trips in CI
- Memory eval cases (`case/memory_eval_cases.json`) are for monitoring only

- [ ] **Step 3: Run `make check`**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && make check
```

- [ ] **Step 4: Commit**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git add -A && git commit -m "docs: update memory eval references for new test strategy"
```

- [ ] **Step 5: Commit spec and plan**

```bash
cd /home/carlos/nanobot-memory-eval-redesign && git add docs/superpowers/specs/2026-03-22-memory-eval-redesign.md docs/superpowers/plans/2026-03-22-memory-eval-redesign.md && git commit -m "docs: add memory eval redesign spec and plan"
```
