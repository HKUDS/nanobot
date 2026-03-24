# Token Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce per-turn token consumption in the nanobot agent without degrading agent behaviour.

**Architecture:** Six targeted, independent changes across context assembly, memory retrieval, tool result caching, and delegation. Each change is isolated to a small number of lines — no cross-cutting refactors. Applied in order of impact/risk ratio (highest bang, lowest risk first).

**Tech Stack:** Python 3.10+, pytest-asyncio (auto mode), ruff, mypy. Run `make lint && make typecheck` after every edit, `make check` before committing.

---

## Estimated Savings Summary

| Task | File(s) | Savings (per turn) | Risk |
|------|---------|-------------------|------|
| T1: Remove redundant MEMORY.md cap call | `memory/store.py` | CPU/I/O (correctness fix) | Low |
| T2: Shrink heuristic summary preview | `tools/result_cache.py` | ~375 tok per large result | Low |
| T3: Cap scratchpad delegation injection | `delegation.py` | Unbounded → ≤1000 tok | Low |
| T4: Skip unresolved scan when irrelevant | `memory/store.py` | I/O + ~30 tok | Low |
| T5: Trim `_get_identity()` memory block | `agent/context.py` | ~130 tok every turn | Medium |
| T6: Shorten skills XML to plain text | `agent/skills.py` | ~40–80 tok every turn | Low |

Total expected steady-state saving: **~600–1,600 tokens per turn** (higher end when tool results are large or skills are numerous).

---

## File Map

| File | Change |
|------|--------|
| `nanobot/agent/context.py` | Trim `_get_identity()` memory instructions block (lines 558–577) |
| `nanobot/agent/skills.py` | Replace XML skills summary with compact plain-text list (lines 111–150) |
| `nanobot/agent/memory/store.py` | Remove redundant Phase-1 `_cap_long_term_text` call; gate unresolved scan on intent |
| `nanobot/agent/tools/result_cache.py` | Reduce heuristic preview from 2000 → 400 chars (line 62) |
| `nanobot/agent/delegation.py` | Cap scratchpad injection at 4000 chars; add `_cap_scratchpad_for_injection` helper |
| `tests/test_token_reduction.py` | New test file covering all six changes |

---

## Task 1: Remove Redundant MEMORY.md Double-Cap

**What:** `get_memory_context()` calls `_cap_long_term_text` twice on the same text:
- **Phase 1** (line ~3655–3658): caps to `memory_md_token_cap` (default 1500 tokens)
- **Phase 3** (line ~3712–3714): caps to `alloc["long_term"]` from the budget allocator

Phase 2 then measures the already-capped text for `section_sizes["long_term"]`. The double call is a redundant CPU/I/O cost — remove Phase 1 and instead pre-cap the *size estimate* passed to the allocator so allocation is informed by the cap without doing the expensive text truncation twice.

**Actual signature of `get_memory_context`:**
```python
def get_memory_context(
    self, *,
    query: str | None = None,
    retrieval_k: int = 6,
    token_budget: int = 900,
    memory_md_token_cap: int = 1500,
    mode: str | None = None,
    recency_half_life_days: float | None = None,
    embedding_provider: str | None = None,
) -> str:
```
It computes `intent`, `long_term`, `profile`, and `retrieved` internally.

**Files:**
- Modify: `nanobot/agent/memory/store.py:3654–3658` (remove Phase 1 cap call)
- Modify: `nanobot/agent/memory/store.py:3696–3706` (pre-cap size for allocator)
- Test: `tests/test_token_reduction.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_token_reduction.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_store():
    """Minimal MemoryStore with mocked I/O for unit tests."""
    from nanobot.memory.store import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    store.workspace = MagicMock()
    store.config = MagicMock()
    store._mem0 = None
    store._graph = None
    store._reranker = None
    return store


# ── Task 1: Remove redundant _cap_long_term_text call ───────────────────────

def test_cap_long_term_text_called_once(monkeypatch):
    """_cap_long_term_text must be called at most once per get_memory_context call."""
    store = make_store()
    call_count = 0
    original = store._cap_long_term_text

    def counting_cap(text: str, cap: int, query: str) -> str:
        nonlocal call_count
        call_count += 1
        return original(text, cap, query)

    monkeypatch.setattr(store, "_cap_long_term_text", counting_cap)

    long_term_text = "fact. " * 300  # ~300 tokens, well within the 1500 cap

    with (
        patch.object(store, "read_long_term", return_value=long_term_text),
        patch.object(store, "read_profile", return_value={}),
        patch.object(store, "retrieve", return_value=[]),
        patch.object(store, "read_events", return_value=[]),
        patch.object(store, "_build_graph_context_lines", return_value=[]),
    ):
        store.get_memory_context(query="test query", token_budget=900, memory_md_token_cap=1500)

    assert call_count == 1, f"_cap_long_term_text called {call_count} times; expected exactly 1"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py::test_cap_long_term_text_called_once -v
```

Expected: FAIL — `_cap_long_term_text` is currently called twice.

- [ ] **Step 3: Apply the fix in store.py**

In `nanobot/agent/memory/store.py`, remove the Phase 1 `_cap_long_term_text` call (~lines 3654–3658):

```python
# ── Phase 1: build raw (untruncated) content for every section ──

long_term_text = long_term.strip() if long_term else ""
# REMOVED: the Phase-1 _cap_long_term_text call that was here
```

In Phase 2 (~lines 3696–3706), pre-cap the size estimate passed to the allocator:

```python
raw_long_term_tokens = self._estimate_tokens(long_term_text)
# Inform allocator of the effective size after the cap it will apply in Phase 3
capped_long_term_tokens = (
    min(raw_long_term_tokens, memory_md_token_cap)
    if memory_md_token_cap > 0
    else raw_long_term_tokens
)

section_sizes: dict[str, int] = {
    "long_term": capped_long_term_tokens,  # was: self._estimate_tokens(long_term_text)
    # ... other sections unchanged ...
}
```

Phase 3 `_cap_long_term_text` call stays — it is now the only call.

- [ ] **Step 4: Run lint and typecheck**

```bash
cd /home/carlos/nanobot && make lint && make typecheck
```

- [ ] **Step 5: Run the tests**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/memory/store.py tests/test_token_reduction.py
git commit -m "fix(memory): remove redundant Phase-1 _cap_long_term_text call in get_memory_context"
```

---

## Task 2: Reduce Heuristic Summary Preview (2000 → 400 chars)

**What:** `_heuristic_summary()` in `result_cache.py` (line 62) includes the first 2000 chars of raw tool output as a "preview". At ~4 chars/token that's ~500 tokens added to context for every large tool result when LLM summarization fails. Reducing to 400 chars cuts this to ~100 tokens — still enough to convey what the output looks like.

**Files:**
- Modify: `nanobot/agent/tools/result_cache.py:62`
- Test: `tests/test_token_reduction.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_token_reduction.py`:

```python
# ── Task 2: Heuristic summary preview length ─────────────────────────────────

from nanobot.tools.result_cache import _heuristic_summary

_PREVIEW_MAX_CHARS = 400


def test_heuristic_summary_preview_length():
    """Heuristic summary preview must not exceed _PREVIEW_MAX_CHARS characters."""
    large_output = "x" * 50_000
    summary = _heuristic_summary("shell", large_output, "cache-key-abc")

    assert "Preview:\n" in summary
    preview_start = summary.index("Preview:\n") + len("Preview:\n")
    preview_end = summary.index("\n...\n", preview_start)
    preview = summary[preview_start:preview_end]

    assert len(preview) <= _PREVIEW_MAX_CHARS, (
        f"Preview is {len(preview)} chars; expected ≤{_PREVIEW_MAX_CHARS}"
    )
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py::test_heuristic_summary_preview_length -v
```

Expected: FAIL — preview is currently 2000 chars.

- [ ] **Step 3: Apply the one-line fix**

In `nanobot/agent/tools/result_cache.py`, line 62:

```python
# Before:
preview = output[:2000]

# After:
preview = output[:400]
```

- [ ] **Step 4: Run lint and typecheck**

```bash
cd /home/carlos/nanobot && make lint && make typecheck
```

- [ ] **Step 5: Run the tests**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py -v
```

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/tools/result_cache.py tests/test_token_reduction.py
git commit -m "fix(cache): reduce heuristic summary preview from 2000 to 400 chars"
```

---

## Task 3: Cap Scratchpad Injection in Delegation

**What:** In `DelegationDispatcher._dispatch_to_role()` (`delegation.py:753–756`), the full scratchpad is appended to the user message with no size limit. In long multi-agent sessions the scratchpad can accumulate tens of thousands of tokens. Add a module-level helper `_cap_scratchpad_for_injection` and cap at 4000 chars with a truncation notice so the sub-agent knows to use `scratchpad_read` for the rest.

**Files:**
- Modify: `nanobot/agent/delegation.py:753–756` (injection block) and near-top (add helper + constant)
- Test: `tests/test_token_reduction.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_token_reduction.py`:

```python
# ── Task 3: Scratchpad injection cap ─────────────────────────────────────────

_SCRATCHPAD_INJECTION_LIMIT = 4000


def _cap_scratchpad_for_injection(content: str, limit: int = _SCRATCHPAD_INJECTION_LIMIT) -> str:
    """Reference implementation used in tests before the real one exists."""
    if len(content) <= limit:
        return content
    return (
        content[:limit]
        + f"\n\n[truncated — {len(content) - limit:,} chars omitted. "
        "Use scratchpad_read tool for full content.]"
    )


def test_scratchpad_injection_is_capped():
    """_cap_scratchpad_for_injection must truncate content over _SCRATCHPAD_INJECTION_LIMIT chars."""
    large_content = "data. " * 5000  # ~30,000 chars
    result = _cap_scratchpad_for_injection(large_content, limit=_SCRATCHPAD_INJECTION_LIMIT)
    assert "[truncated" in result
    assert len(result) <= _SCRATCHPAD_INJECTION_LIMIT + 200  # +200 for truncation notice


def test_scratchpad_injection_unchanged_when_small():
    """_cap_scratchpad_for_injection must not modify content under the limit."""
    small_content = "short content"
    result = _cap_scratchpad_for_injection(small_content, limit=_SCRATCHPAD_INJECTION_LIMIT)
    assert result == small_content
    assert "[truncated" not in result
```

- [ ] **Step 2: Run to confirm the test passes (tests the helper logic)**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py::test_scratchpad_injection_is_capped tests/test_token_reduction.py::test_scratchpad_injection_unchanged_when_small -v
```

Expected: PASS (testing the reference logic). Now wire it into delegation.

- [ ] **Step 3: Add the helper to delegation.py**

In `nanobot/agent/delegation.py`, after the imports section, add:

```python
_SCRATCHPAD_INJECTION_LIMIT: int = 4_000


def _cap_scratchpad_for_injection(
    content: str, limit: int = _SCRATCHPAD_INJECTION_LIMIT
) -> str:
    """Truncate scratchpad content for delegation injection to avoid context bloat."""
    if len(content) <= limit:
        return content
    return (
        content[:limit]
        + f"\n\n[truncated — {len(content) - limit:,} chars omitted. "
        "Use scratchpad_read tool for full content.]"
    )
```

- [ ] **Step 4: Update the injection block (lines ~753–756)**

```python
# Before:
if role.name in ("pm", "writing", "general") and self.scratchpad:
    scratchpad_content = self.scratchpad.read()
    if scratchpad_content and scratchpad_content != "Scratchpad is empty.":
        user_content += f"\n\n## Prior Agent Findings (Scratchpad)\n{scratchpad_content}"

# After:
if role.name in ("pm", "writing", "general") and self.scratchpad:
    scratchpad_content = self.scratchpad.read()
    if scratchpad_content and scratchpad_content != "Scratchpad is empty.":
        user_content += (
            f"\n\n## Prior Agent Findings (Scratchpad)\n"
            + _cap_scratchpad_for_injection(scratchpad_content)
        )
```

- [ ] **Step 5: Update the test to import from the real module**

Replace the local reference implementation in the test with the real import:

```python
from nanobot.agent.delegation import _cap_scratchpad_for_injection, _SCRATCHPAD_INJECTION_LIMIT
```

Remove the local `_cap_scratchpad_for_injection` definition and `_SCRATCHPAD_INJECTION_LIMIT = 4000` from the test file.

- [ ] **Step 6: Run lint and typecheck**

```bash
cd /home/carlos/nanobot && make lint && make typecheck
```

- [ ] **Step 7: Run the tests**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py -v
```

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/delegation.py tests/test_token_reduction.py
git commit -m "fix(delegation): cap scratchpad injection at 4000 chars to prevent context bloat"
```

---

## Task 4: Gate Unresolved Events Scan on Intent

**What:** `get_memory_context()` always calls `self.read_events(limit=60)` regardless of query intent (line ~3685). This is unnecessary I/O and adds ~30 tokens of unresolved tasks for queries where they are irrelevant (e.g. `fact_lookup`, `chitchat`). Gate the scan on the intents that benefit: `planning`, `debug`, `conflict`, `reflection`, `task`.

Define `_UNRESOLVED_INTENTS` as a **module-level constant** (not inside the method).

**Files:**
- Modify: `nanobot/agent/memory/store.py:3685` and near-top of module (add constant)
- Test: `tests/test_token_reduction.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_token_reduction.py`:

```python
# ── Task 4: Gate unresolved events scan on intent ────────────────────────────

def test_read_events_not_called_for_fact_lookup(monkeypatch):
    """read_events must not be called when the inferred intent is 'fact_lookup'."""
    store = make_store()
    read_events_called = False

    def mock_read_events(limit: int = 60) -> list:
        nonlocal read_events_called
        read_events_called = True
        return []

    with (
        patch.object(store, "read_long_term", return_value=""),
        patch.object(store, "read_profile", return_value={}),
        patch.object(store, "retrieve", return_value=[]),
        patch.object(store, "read_events", side_effect=mock_read_events),
        patch.object(store, "_build_graph_context_lines", return_value=[]),
    ):
        # "what is the capital of France" infers as fact_lookup
        store.get_memory_context(query="what is the capital of France", token_budget=900)

    assert not read_events_called, "read_events was called for a fact_lookup query"


def test_read_events_called_for_planning(monkeypatch):
    """read_events must be called when the query infers a planning intent."""
    store = make_store()
    read_events_called = False

    def mock_read_events(limit: int = 60) -> list:
        nonlocal read_events_called
        read_events_called = True
        return []

    with (
        patch.object(store, "read_long_term", return_value=""),
        patch.object(store, "read_profile", return_value={}),
        patch.object(store, "retrieve", return_value=[]),
        patch.object(store, "read_events", side_effect=mock_read_events),
        patch.object(store, "_build_graph_context_lines", return_value=[]),
    ):
        # "plan the sprint tasks" should infer as planning
        store.get_memory_context(query="plan the sprint tasks for next week", token_budget=900)

    assert read_events_called, "read_events was NOT called for a planning query"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py::test_read_events_not_called_for_fact_lookup -v
```

Expected: FAIL — `read_events` is currently called unconditionally.

- [ ] **Step 3: Add the module-level constant to store.py**

Near the top of `nanobot/agent/memory/store.py` (after the imports, with the other module constants):

```python
_UNRESOLVED_INTENTS: frozenset[str] = frozenset(
    {"planning", "debug", "conflict", "reflection", "task"}
)
```

- [ ] **Step 4: Gate the scan in get_memory_context**

Replace line ~3685 in the method body:

```python
# Before:
unresolved = self._recent_unresolved(self.read_events(limit=60), max_items=6)

# After:
intent = self._infer_retrieval_intent(query or "")  # already computed above — reuse the variable
unresolved: list[dict[str, Any]] = (
    self._recent_unresolved(self.read_events(limit=60), max_items=6)
    if intent in _UNRESOLVED_INTENTS
    else []
)
```

Note: `intent` is already assigned earlier in the method (`intent = self._infer_retrieval_intent(query or "")`). Do not recompute it — just reference the existing variable.

- [ ] **Step 5: Run lint and typecheck**

```bash
cd /home/carlos/nanobot && make lint && make typecheck
```

- [ ] **Step 6: Run the tests**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py -v
```

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/memory/store.py tests/test_token_reduction.py
git commit -m "perf(memory): skip unresolved events scan for non-planning intents"
```

---

## Task 5: Trim `_get_identity()` Memory Instructions

**What:** The 9-bullet "Using Your Memory Context" block in `_get_identity()` (`context.py:558–577`) is ~130 tokens sent every single turn. Reduce to 3 essential bullets. The detailed instructions are mostly redundant with how modern Claude models naturally use injected context. The remaining bullets cover entity graph, profile trust, completeness, and "memory overrides training data" — cut those, they don't change behaviour meaningfully for this model.

**Risk note:** Run `make memory-eval` after this task to confirm retrieval quality metrics don't regress.

**Files:**
- Modify: `nanobot/agent/context.py:558–577`
- Test: `tests/test_token_reduction.py`

- [ ] **Step 1: Write the test**

Add to `tests/test_token_reduction.py`:

```python
# ── Task 5: Trim _get_identity() memory block ────────────────────────────────

def test_identity_memory_block_under_token_limit():
    """The memory instructions in _get_identity() must be ≤60 tokens (~240 chars)."""
    from nanobot.agent.context import ContextBuilder
    from pathlib import Path

    builder = ContextBuilder.__new__(ContextBuilder)
    builder.workspace = Path("/tmp")
    identity = builder._get_identity()

    marker = "## Using Your Memory Context"
    assert marker in identity, "Memory context instructions section not found"

    start = identity.index(marker) + len(marker)
    rest = identity[start:]
    next_section = rest.find("\n## ")
    section_text = rest[:next_section].strip() if next_section != -1 else rest.strip()

    char_count = len(section_text)
    assert char_count <= 240, (
        f"Memory instructions are {char_count} chars (~{char_count // 4} tokens); "
        f"expected ≤240 chars (~60 tokens). Trim to 3 essential bullets."
    )
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py::test_identity_memory_block_under_token_limit -v
```

Expected: FAIL — section currently ~550 chars (~130 tokens).

- [ ] **Step 3: Apply the fix in context.py**

Replace lines 558–577 of `nanobot/agent/context.py` with:

```python
## Using Your Memory Context
- Prefer memory over general knowledge — if the Memory section answers the question, use it directly.
- Cite exact values verbatim (names, numbers, technical terms) — do not paraphrase.
- Answer from memory first; only call tools for information not already in your memory context.
```

- [ ] **Step 4: Run lint and typecheck**

```bash
cd /home/carlos/nanobot && make lint && make typecheck
```

- [ ] **Step 5: Run the tests**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py -v
```

- [ ] **Step 6: Run the full test suite**

```bash
cd /home/carlos/nanobot && make test
```

- [ ] **Step 7: Run memory eval to check for regressions**

```bash
cd /home/carlos/nanobot && make memory-eval
```

Expected: metrics at or above baseline. If any metric regresses >2%, restore the trimmed bullets that correspond to the failing cases before committing.

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/context.py tests/test_token_reduction.py
git commit -m "perf(context): trim memory instructions in _get_identity from 9 bullets to 3"
```

---

## Task 6: Replace Skills XML Summary with Compact Plain Text

**What:** `SkillsLoader.build_skills_summary()` (`skills.py:111–150`) emits a multi-line XML block for every skill every turn. A single-line-per-skill plain text format conveys the same information in ~50% fewer tokens. The method calls `self.list_skills(filter_unavailable=False)` internally — the test must mock that, not a non-existent `self.skills` attribute.

Also update the docstring (currently says "XML-formatted") to avoid `make prompt-check` failures.

**Files:**
- Modify: `nanobot/agent/skills.py:111–150`
- Test: `tests/test_token_reduction.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_token_reduction.py`:

```python
# ── Task 6: Skills summary format ────────────────────────────────────────────

def test_skills_summary_is_compact(tmp_path, monkeypatch):
    """Skills summary must use one line per skill, not multi-line XML."""
    from nanobot.agent.skills import SkillsLoader

    loader = SkillsLoader(workspace=tmp_path)

    # Stub list_skills to return two fake skill dicts without filesystem access
    fake_skills = [
        {"name": "weather", "path": str(tmp_path / "weather/SKILL.md"), "available": True},
        {"name": "github", "path": str(tmp_path / "github/SKILL.md"), "available": False},
    ]
    monkeypatch.setattr(loader, "list_skills", lambda filter_unavailable=True: fake_skills)
    monkeypatch.setattr(loader, "_get_skill_description", lambda name: f"{name} description")
    monkeypatch.setattr(loader, "_get_skill_meta", lambda name: {})
    monkeypatch.setattr(loader, "_check_requirements", lambda meta: True)

    summary = loader.build_skills_summary()

    assert "<skill" not in summary, "Skills summary must not use XML <skill> tags"
    assert "<skills>" not in summary, "Skills summary must not use <skills> root element"

    # Each skill should appear on exactly one line
    skill_lines_weather = [l for l in summary.splitlines() if "weather" in l]
    skill_lines_github = [l for l in summary.splitlines() if "github" in l]
    assert len(skill_lines_weather) == 1, f"'weather' appears on {len(skill_lines_weather)} lines"
    assert len(skill_lines_github) == 1, f"'github' appears on {len(skill_lines_github)} lines"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py::test_skills_summary_is_compact -v
```

Expected: FAIL — currently outputs multi-line XML.

- [ ] **Step 3: Apply the fix in skills.py**

Replace the `build_skills_summary` method body (lines 111–150):

```python
def build_skills_summary(self) -> str:
    """Build a compact plain-text listing of all skills (one line per skill).

    The agent can load the full skill content via read_file when needed.
    """
    all_skills = self.list_skills(filter_unavailable=False)
    if not all_skills:
        return ""

    lines = ["## Available Skills"]
    for s in all_skills:
        skill_meta = self._get_skill_meta(s["name"])
        available = self._check_requirements(skill_meta)
        status = "✓" if available else "✗"
        desc = self._get_skill_description(s["name"])
        lines.append(f"- {status} **{s['name']}**: {desc}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run lint and typecheck**

```bash
cd /home/carlos/nanobot && make lint && make typecheck
```

- [ ] **Step 5: Run the tests**

```bash
cd /home/carlos/nanobot && python -m pytest tests/test_token_reduction.py -v
```

- [ ] **Step 6: Run the full validation**

```bash
cd /home/carlos/nanobot && make check
```

Expected: all checks pass.

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/skills.py tests/test_token_reduction.py
git commit -m "perf(skills): replace XML skills summary with compact plain-text list"
```

---

## Final Validation

- [ ] **Run the complete check**

```bash
cd /home/carlos/nanobot && make check
```

Expected: lint ✓, typecheck ✓, import-check ✓, prompt-check ✓, tests ✓.

- [ ] **Verify token savings with a manual estimate**

```bash
cd /home/carlos/nanobot && python3 - <<'EOF'
from nanobot.agent.context import ContextBuilder
from pathlib import Path

b = ContextBuilder.__new__(ContextBuilder)
b.workspace = Path("/tmp")
identity = b._get_identity()
print(f"Identity block: {len(identity)} chars (~{len(identity)//4} tokens)")
EOF
```

Expected: identity block ≤1800 chars (~450 tok) vs ~2200 chars before.
