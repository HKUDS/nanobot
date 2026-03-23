# Memory Evaluation Redesign: Contracts + LLM Round-Trips + Observability

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Replace the fragile `memory-eval` CI benchmark with behavioral
contract tests, real-LLM round-trip tests, and non-gating observability.

## Problem

The current `memory-eval` CI gate is a deterministic BM25 retrieval benchmark
that seeds 44 pre-authored events and runs 38 canned queries with hardcoded
expected results. It has fundamental problems:

1. **Tests the wrong thing.** It tests BM25 keyword positions, not whether
   the agent remembers what the user told it. Pre-authored events bypass the
   extraction pipeline entirely — the hardest and most error-prone part.

2. **Brittle to refactoring.** Any scoring change breaks the threshold gate,
   even when memory quality is unchanged. We experienced this: a pure structural
   refactoring of the retriever broke CI despite no behavioral intent to change.

3. **Only tests one path.** The mem0 vector retrieval path (the primary path
   in production) is never exercised. Only the BM25 fallback is tested.

4. **No round-trip coverage.** No test verifies that information survives
   the full lifecycle: user says X → consolidation extracts it → next turn
   retrieves it in context. This is the core user-facing promise.

5. **False positives and negatives.** Synonym maps differ between eval and
   retrieval, causing false negatives. Permissive substring matching causes
   false positives. `required_min_hits` relaxation masks partial failures.

## Solution: Three Layers

### Layer 1: Behavioral Contract Tests (CI gate, no LLM)

**File:** `tests/contract/test_memory_contracts.py` (expand existing)

Tests that assert *invariants* — properties that must hold regardless of
scoring formula, retrieval backend, or internal refactoring. No LLM calls.
Fast, deterministic, run as part of `make test`.

These test the **engine** — given well-formed inputs, does the machinery
produce correct outputs?

| Contract | What it verifies |
|----------|-----------------|
| Preference round-trip | Store preference event → retrieve by keyword → found |
| Fact round-trip | Store fact event → retrieve by keyword → found |
| Supersession ordering | Superseded event ranks below its active replacement |
| Recency ordering | Newer event ranks above older for same topic |
| Negative query | Irrelevant query returns no matching events |
| High-salience surfacing | High-salience event appears in top-3 for keyword match |
| Dedup idempotency | Appending same event twice yields 1 stored event |
| Type-appropriate retrieval | Task query returns episodic events above semantic ones |
| Context assembly completeness | get_memory_context returns non-empty string with profile + events |

**Test structure:**
- Each test seeds data via `ingester.append_events()` (direct, no LLM)
- Queries via `retriever.retrieve()` or `store.get_memory_context()`
- Asserts invariants (keyword presence, relative ordering, count)
- Uses `tmp_path`, `embedding_provider="hash"`, `vector_backend="json"`

### Layer 2: End-to-End Round-Trip Tests (CI gate, real LLM)

**File:** `tests/test_memory_roundtrip.py` (new)

Tests the **full system including the LLM**. A real LLM reads a real
conversation, decides what to extract, and the pipeline stores and retrieves
it. This is what the user experiences.

| Scenario | Lifecycle |
|----------|-----------|
| Preference consolidation | User says preference → consolidate with real LLM → get_memory_context → assert preference surfaces |
| Fact storage | User states fact → consolidate → retrieve → fact found |
| Fact correction | Seed old fact → user corrects → consolidate → new fact in context, old not prominent |
| Multi-turn accumulation | 3 turns, each consolidated → all 3 facts retrievable |
| Context assembly | Seed profile + consolidate conversation → get_memory_context returns complete context |

**LLM configuration:**
- Model: `gpt-4o-mini` (cheap, fast, sufficient for extraction)
- Called via `litellm` (the project's existing provider)
- Cost: ~30 LLM calls × ~500 tokens ≈ $0.01-0.05 per run
- Speed: ~10-15 seconds for all scenarios

**Assertion style:**
- Fuzzy keyword matching: `assert "dark mode" in context.lower()`
- NOT exact string match on LLM output
- NOT position-based assertions (ranking can vary)
- Each assertion checks "did the information survive the pipeline?"

**CI handling:**
- Separate CI job (not in main `test` matrix)
- Requires `OPENAI_API_KEY` secret (or `LITELLM_API_KEY`)
- Retries once on failure (handles transient API issues)
- Skipped if no API key is available (contributor PRs from forks)
- Marked with `@pytest.mark.llm` for selective running

**Failure semantics:**
- If the LLM extracts nothing (empty events), the test fails — this is a
  real regression (prompt or extraction logic changed)
- If the LLM extracts something reasonable but with different wording, the
  test passes — fuzzy assertions handle this
- If the API is unreachable, the job retries once, then marks as skipped
  (not failed)

### Layer 3: Observability (non-gating, dashboard)

Move the existing retrieval benchmark to Langfuse trend monitoring.

- Rename `scripts/memory_eval_ci.py` → `scripts/memory_eval_trend.py`
- Remove `--strict` exit code (always exit 0)
- Modify `.github/workflows/memory-eval-trend.yml` to be non-blocking
  (remove `required` status check)
- Results published to Langfuse for trend dashboards
- `make memory-eval` becomes advisory: runs the benchmark, prints results,
  never fails

This preserves the 38-case benchmark for monitoring without gating CI.

## What Gets Deleted

| File/Component | Action |
|----------------|--------|
| `case/memory_eval_baseline.json` | Delete — no more threshold gating |
| `Makefile` `memory-eval` target | Modify — remove `--strict`, advisory only |
| `.github/workflows/memory-eval-trend.yml` | Modify — non-blocking |
| `EvalRunner.evaluate_retrieval_cases()` | Keep — used by trend monitoring |
| `scripts/memory_eval_ci.py` | Rename to `memory_eval_trend.py` |

## What Gets Created

| File | Purpose |
|------|---------|
| `tests/contract/test_memory_contracts.py` | Expanded with ~9 contract tests |
| `tests/test_memory_roundtrip.py` | ~5 LLM round-trip scenarios |
| `pyproject.toml` | `@pytest.mark.llm` marker registration (in `[tool.pytest.ini_options]` `markers` list) |

## What Gets Kept

| File | Reason |
|------|--------|
| `case/memory_eval_cases.json` | Used by trend monitoring |
| `case/memory_seed_events.jsonl` | Reused by contract tests for seeding |
| `case/memory_seed_profile.json` | Reused by contract tests for seeding |
| `nanobot/agent/memory/eval.py` | Used by trend monitoring + rollout gates |

## Execution Order

1. **Expand contract tests** — add 9 invariant tests to existing file
2. **Create round-trip tests** — new file with 5 LLM scenarios
3. **Rename eval script + update Makefile** — `memory_eval_ci.py` →
   `memory_eval_trend.py`, Makefile becomes advisory (done together to
   keep `make memory-eval` functional throughout)
4. **Delete baseline** — remove `memory_eval_baseline.json`
5. **Modify CI** — add LLM test job, update `memory-eval-trend.yml` to be
   non-blocking and update path trigger to the renamed script
6. **Register pytest marker** — add `llm` to `pyproject.toml` markers
7. **Update docs** — CLAUDE.md, test-strategy.md

## Testing the Tests

Before merging:
- Contract tests pass locally: `pytest tests/contract/test_memory_contracts.py -v`
- Round-trip tests pass locally: `pytest tests/test_memory_roundtrip.py -v -m llm`
  (requires API key)
- `make check` passes (contract tests run as part of test suite)
- `make memory-eval` runs without error (advisory, no failure)

## Why This Is Better

| Dimension | Old eval | New eval |
|-----------|----------|----------|
| What it tests | BM25 keyword positions | Full pipeline: extract → store → retrieve → context |
| Stability | Breaks on scoring refactors | Stable — tests invariants and round-trips |
| Extraction coverage | None (pre-authored events) | Real LLM extraction |
| Context assembly | Not tested | Tested in contracts + round-trips |
| False negatives | Synonym map mismatches | Fuzzy keyword assertions |
| False positives | Permissive substring matching | Tests actual user scenarios |
| CI speed | ~5 seconds | ~15 seconds (contracts) + ~15 seconds (LLM) |
| Cost per run | $0 | ~$0.03 |

## Out of Scope

- mem0 vector retrieval testing (requires real embedding model — future work)
- LLM-as-judge evaluation (useful for monitoring, not for CI)
- Knowledge graph retrieval testing
- Performance benchmarking
- Rewriting `eval.py` internals (it's used for trend monitoring as-is)
