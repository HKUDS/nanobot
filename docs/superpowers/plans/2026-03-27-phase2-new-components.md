# Phase 2: Introduce New Components — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the new standalone components for the redesigned agent — guardrails, working memory types, prompt templates, and procedural memory storage. These exist alongside the current code with no wiring yet.

**Architecture:** All new components are standalone and independently testable. They don't replace or modify any existing functionality. They are building blocks for Phase 3 (rewire the loop) and Phase 5 (procedural memory).

**Tech Stack:** Python 3.10+, ruff, mypy, pytest, SQLite

**Spec:** `docs/superpowers/specs/2026-03-27-agent-cognitive-redesign.md`, Phase 2 + Component Designs

**IMPORTANT:** These components are standalone. Do NOT wire them into the existing agent loop, factory, or message processor. That happens in Phases 3-5. Every task produces a codebase that passes `make pre-push` (including clean mypy cache).

---

## File Map

### Files to CREATE

| File | LOC Target | Purpose |
|------|-----------|---------|
| `nanobot/agent/turn_guardrails.py` | ~150 | Intervention, Guardrail protocol, GuardrailChain, 5 guardrail classes |
| `tests/test_guardrails.py` | ~200 | Unit tests for all guardrails + chain |
| `nanobot/templates/prompts/reasoning.md` | ~40 | Reasoning protocol prompt |
| `nanobot/templates/prompts/tool_guide.md` | ~25 | Tool selection guide prompt |
| `nanobot/templates/prompts/self_check.md` | ~10 | Self-verification prompt |
| `nanobot/memory/strategy.py` | ~100 | Strategy dataclass + StrategyStore |
| `tests/test_strategy_store.py` | ~120 | CRUD tests for strategy storage |

### Files to MODIFY

| File | Change |
|------|--------|
| `nanobot/agent/turn_types.py` | Add ToolAttempt dataclass |
| `prompts_manifest.json` | Add entries for 3 new prompt templates |

---

## Tasks

### Task 1: Add ToolAttempt dataclass to turn_types.py

**Files:**
- Modify: `nanobot/agent/turn_types.py`
- Test: `tests/test_turn_types.py` (extend existing or create)

- [ ] **Step 1: Write the test**

```python
# In tests/test_turn_types.py (create if doesn't exist, or add to existing)

from nanobot.agent.turn_types import ToolAttempt


class TestToolAttempt:
    def test_creation(self):
        attempt = ToolAttempt(
            tool_name="exec",
            arguments={"command": "obsidian search query=DS10540"},
            success=True,
            output_empty=True,
            output_snippet="No matches found.",
            iteration=1,
        )
        assert attempt.tool_name == "exec"
        assert attempt.success is True
        assert attempt.output_empty is True
        assert attempt.iteration == 1

    def test_frozen(self):
        attempt = ToolAttempt(
            tool_name="exec",
            arguments={},
            success=True,
            output_empty=False,
            output_snippet="data",
            iteration=1,
        )
        import pytest
        with pytest.raises(AttributeError):
            attempt.tool_name = "other"  # type: ignore[misc]

    def test_output_snippet_truncation_is_caller_responsibility(self):
        """ToolAttempt stores whatever snippet is given; truncation is the caller's job."""
        long_text = "x" * 500
        attempt = ToolAttempt(
            tool_name="read_file",
            arguments={"path": "/tmp/f"},
            success=True,
            output_empty=False,
            output_snippet=long_text,
            iteration=2,
        )
        assert len(attempt.output_snippet) == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/test_turn_types.py -v -k "ToolAttempt" 2>&1 | tail -10`
Expected: ImportError or AttributeError (ToolAttempt doesn't exist yet)

- [ ] **Step 3: Add ToolAttempt to turn_types.py**

Add this dataclass to `nanobot/agent/turn_types.py`, after the existing imports but before TurnState:

```python
@dataclass(slots=True, frozen=True)
class ToolAttempt:
    """Record of a single tool call for working memory.

    Enables guardrails to detect patterns like repeated empty results,
    strategy loops, and skill tunnel vision.
    """

    tool_name: str
    arguments: dict[str, Any]
    success: bool
    output_empty: bool      # True when success=True but no meaningful data returned
    output_snippet: str     # First 200 chars of output for pattern detection
    iteration: int
```

Add `ToolAttempt` to the module's `__all__` if one exists, or to the `nanobot/agent/__init__.py` exports if appropriate.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/test_turn_types.py -v -k "ToolAttempt"`
Expected: 3 passed

- [ ] **Step 5: Run make lint && make typecheck**

Run: `cd ../nanobot-phase2-new-components && make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/turn_types.py tests/test_turn_types.py
git commit -m "feat(agent): add ToolAttempt dataclass for working memory"
```

---

### Task 2: Create the guardrail layer

This is the largest task — create the full guardrail infrastructure and all 5 guardrails.

**Files:**
- Create: `nanobot/agent/turn_guardrails.py`
- Create: `tests/test_guardrails.py`

- [ ] **Step 1: Write tests for Intervention and GuardrailChain**

```python
# tests/test_guardrails.py

from __future__ import annotations

from nanobot.agent.turn_guardrails import (
    EmptyResultRecovery,
    FailureEscalation,
    GuardrailChain,
    Intervention,
    NoProgressBudget,
    RepeatedStrategyDetection,
    SkillTunnelVision,
)
from nanobot.agent.turn_types import ToolAttempt


def _attempt(
    tool: str = "exec",
    args: dict | None = None,
    success: bool = True,
    empty: bool = False,
    snippet: str = "data",
    iteration: int = 1,
) -> ToolAttempt:
    return ToolAttempt(
        tool_name=tool,
        arguments=args or {},
        success=success,
        output_empty=empty,
        output_snippet=snippet,
        iteration=iteration,
    )


class TestIntervention:
    def test_creation(self):
        i = Intervention(
            source="test",
            message="do something",
            severity="hint",
            strategy_tag="test_tag",
        )
        assert i.source == "test"
        assert i.severity == "hint"
        assert i.strategy_tag == "test_tag"

    def test_frozen(self):
        import pytest
        i = Intervention(source="x", message="y", severity="hint")
        with pytest.raises(AttributeError):
            i.source = "z"  # type: ignore[misc]


class TestGuardrailChain:
    def test_returns_none_when_all_pass(self):
        chain = GuardrailChain([])
        result = chain.check([], [])
        assert result is None

    def test_first_intervention_wins(self):
        """When multiple guardrails would fire, only the first one returns."""
        class AlwaysFires:
            name = "always"
            def check(self, state, latest):
                return Intervention(source="always", message="fired", severity="hint")

        class AlsoFires:
            name = "also"
            def check(self, state, latest):
                return Intervention(source="also", message="also fired", severity="hint")

        chain = GuardrailChain([AlwaysFires(), AlsoFires()])
        result = chain.check([], [])
        assert result is not None
        assert result.source == "always"

    def test_skips_non_firing_guardrails(self):
        class NeverFires:
            name = "never"
            def check(self, state, latest):
                return None

        class AlwaysFires:
            name = "always"
            def check(self, state, latest):
                return Intervention(source="always", message="fired", severity="hint")

        chain = GuardrailChain([NeverFires(), AlwaysFires()])
        result = chain.check([], [])
        assert result is not None
        assert result.source == "always"
```

- [ ] **Step 2: Write tests for EmptyResultRecovery**

```python
class TestEmptyResultRecovery:
    def test_no_fire_on_successful_result(self):
        g = EmptyResultRecovery()
        latest = [_attempt(success=True, empty=False)]
        result = g.check(latest, latest)
        assert result is None

    def test_no_fire_on_failed_result(self):
        g = EmptyResultRecovery()
        latest = [_attempt(success=False, empty=False)]
        result = g.check(latest, latest)
        assert result is None

    def test_fires_hint_on_first_empty(self):
        g = EmptyResultRecovery()
        latest = [_attempt(success=True, empty=True)]
        result = g.check(latest, latest)
        assert result is not None
        assert result.severity == "hint"
        assert "alternative approach" in result.message

    def test_fires_directive_on_second_empty(self):
        g = EmptyResultRecovery()
        prior = [_attempt(tool="exec", success=True, empty=True, iteration=1)]
        latest = [_attempt(tool="exec", success=True, empty=True, iteration=2)]
        all_attempts = prior + latest
        result = g.check(all_attempts, latest)
        assert result is not None
        assert result.severity == "directive"
        assert "STOP" in result.message

    def test_strategy_tag_present(self):
        g = EmptyResultRecovery()
        latest = [_attempt(success=True, empty=True)]
        result = g.check(latest, latest)
        assert result is not None
        assert result.strategy_tag is not None
```

- [ ] **Step 3: Write tests for RepeatedStrategyDetection**

```python
class TestRepeatedStrategyDetection:
    def test_no_fire_on_first_call(self):
        g = RepeatedStrategyDetection()
        latest = [_attempt(args={"command": "search"})]
        result = g.check(latest, latest)
        assert result is None

    def test_no_fire_on_different_args(self):
        g = RepeatedStrategyDetection()
        prior = [
            _attempt(args={"command": "search foo"}, iteration=1),
            _attempt(args={"command": "list bar"}, iteration=2),
        ]
        latest = [_attempt(args={"command": "read baz"}, iteration=3)]
        result = g.check(prior + latest, latest)
        assert result is None

    def test_fires_on_third_similar_call(self):
        g = RepeatedStrategyDetection()
        args = {"command": "obsidian search query=DS10540"}
        prior = [
            _attempt(args=args, iteration=1),
            _attempt(args=args, iteration=2),
        ]
        latest = [_attempt(args=args, iteration=3)]
        result = g.check(prior + latest, latest)
        assert result is not None
        assert result.severity == "override"
        assert "different strategy" in result.message.lower() or "MUST" in result.message
```

- [ ] **Step 4: Write tests for SkillTunnelVision**

```python
class TestSkillTunnelVision:
    def test_no_fire_before_iteration_3(self):
        g = SkillTunnelVision()
        attempts = [_attempt(tool="exec", empty=True, iteration=i) for i in range(1, 3)]
        latest = [attempts[-1]]
        result = g.check(attempts, latest, iteration=2)
        assert result is None

    def test_fires_when_all_exec_no_data(self):
        g = SkillTunnelVision()
        attempts = [_attempt(tool="exec", empty=True, iteration=i) for i in range(1, 7)]
        latest = [attempts[-1]]
        result = g.check(attempts, latest, iteration=4)
        assert result is not None
        assert result.severity == "directive"
        assert "list_dir" in result.message or "base tools" in result.message

    def test_no_fire_when_exec_returns_data(self):
        g = SkillTunnelVision()
        attempts = [
            _attempt(tool="exec", empty=True, iteration=1),
            _attempt(tool="exec", empty=False, iteration=2),
            _attempt(tool="exec", empty=True, iteration=3),
        ]
        latest = [attempts[-1]]
        result = g.check(attempts, latest, iteration=4)
        assert result is None

    def test_no_fire_when_mixed_tools(self):
        g = SkillTunnelVision()
        attempts = [
            _attempt(tool="exec", empty=True, iteration=1),
            _attempt(tool="list_dir", empty=True, iteration=2),
            _attempt(tool="exec", empty=True, iteration=3),
        ]
        latest = [attempts[-1]]
        result = g.check(attempts, latest, iteration=4)
        assert result is None
```

- [ ] **Step 5: Write tests for NoProgressBudget**

```python
class TestNoProgressBudget:
    def test_no_fire_before_iteration_4(self):
        g = NoProgressBudget()
        attempts = [_attempt(empty=True, iteration=i) for i in range(1, 4)]
        result = g.check(attempts, [attempts[-1]], iteration=3)
        assert result is None

    def test_fires_when_no_useful_data_after_4(self):
        g = NoProgressBudget()
        attempts = [_attempt(empty=True, iteration=i) for i in range(1, 5)]
        result = g.check(attempts, [attempts[-1]], iteration=4)
        assert result is not None
        assert result.severity == "override"
        assert "stop calling tools" in result.message.lower()

    def test_no_fire_when_some_useful_data(self):
        g = NoProgressBudget()
        attempts = [
            _attempt(empty=True, iteration=1),
            _attempt(empty=False, iteration=2),
            _attempt(empty=True, iteration=3),
            _attempt(empty=True, iteration=4),
        ]
        result = g.check(attempts, [attempts[-1]], iteration=4)
        assert result is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/test_guardrails.py -v 2>&1 | tail -10`
Expected: ImportError (turn_guardrails module doesn't exist yet)

- [ ] **Step 7: Implement turn_guardrails.py**

Create `nanobot/agent/turn_guardrails.py` with the complete implementation. Follow the design from the spec exactly:

- `Intervention` dataclass (frozen, slots): source, message, severity, strategy_tag
- `Guardrail` Protocol: name property, check method
- `GuardrailChain`: takes list of guardrails, first-intervention-wins
- `EmptyResultRecovery`: hint on first empty, directive on second
- `RepeatedStrategyDetection`: fires when same tool+args appears 3+ times
- `SkillTunnelVision`: fires when all exec calls return no data after iteration 3
- `NoProgressBudget`: fires when 4+ iterations with no useful data
- `FailureEscalation`: fires when tool fails N times (use existing ToolCallTracker thresholds)

**Key design rules:**
- GuardrailChain.check() takes `all_attempts: list[ToolAttempt]` and `latest_results: list[ToolAttempt]` and optionally `iteration: int`
- Each guardrail's check() receives the same parameters
- Guardrails are pure functions (except FailureEscalation which may access tracker)
- All guardrails in one file while under 200 LOC
- Start with `from __future__ import annotations`

Note: FailureEscalation interacts with `ToolCallTracker` from `nanobot/agent/failure.py`. For now, implement it as a stub that returns None — the full integration happens in Phase 3 when the tracker is wired in. Add a comment: `# TODO Phase 3: wire ToolCallTracker`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/test_guardrails.py -v`
Expected: All tests pass

- [ ] **Step 9: Run make lint && make typecheck**

Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add nanobot/agent/turn_guardrails.py tests/test_guardrails.py
git commit -m "feat(agent): add guardrail layer with 5 initial guardrails

Introduce Intervention dataclass, Guardrail protocol, GuardrailChain
(first-intervention-wins), and 5 guardrails: EmptyResultRecovery,
RepeatedStrategyDetection, SkillTunnelVision, NoProgressBudget,
FailureEscalation (stub).

Part of Phase 2: agent cognitive core redesign (new components)."
```

---

### Task 3: Create prompt templates

**Files:**
- Create: `nanobot/templates/prompts/reasoning.md`
- Create: `nanobot/templates/prompts/tool_guide.md`
- Create: `nanobot/templates/prompts/self_check.md`
- Modify: `prompts_manifest.json`

- [ ] **Step 1: Create reasoning.md**

Create `nanobot/templates/prompts/reasoning.md`:

```markdown
# Reasoning Protocol

## Before Taking Action

When you receive a task, work through these steps before calling any tool:

1. **What does the user need?**
   Find something? Read content? Create something? Modify? Summarize?

2. **What am I looking for?**
   Identify the target type:
   - A project code or identifier → likely a FOLDER or FILE NAME
   - A topic or keyword → likely FILE CONTENT
   - A tag, property, or date → likely METADATA
   - A specific document → likely a FILE PATH

3. **Which tool or command matches the target type?**
   Match by purpose, not by name similarity:
   - Find by name → list_dir, or skill commands that list/browse
   - Search content → grep/search commands
   - Read known file → read_file
   - Explore structure → list_dir first, then narrow down

4. **What is my fallback?**
   Before executing, know what you will try if this returns nothing.
   Always have a Plan B that uses a DIFFERENT approach, not the same
   tool with tweaked arguments.

## When a Tool Returns Empty Results

STOP. Do not report "not found" to the user.

"No results" means your APPROACH may be wrong — not that the data
doesn't exist. The user told you it exists.

Ask yourself:
- Could the search term be a folder name instead of file content?
- Could it be a file name instead of a tag?
- Should I list the directory structure instead of searching?

Try your fallback approach before responding.

## When a Tool Returns an Error

Read the error message. Classify it:
- Wrong arguments → fix the syntax and retry
- Command not found → use a different command
- Permission denied → try a different approach entirely
- Timeout → try a simpler operation

Do not retry the same failing command unchanged.

## Fallback Principle

Your base tools (list_dir, read_file) always work. If specialized
tools or skill commands fail, fall back to the filesystem.
The filesystem is ground truth.
```

- [ ] **Step 2: Create tool_guide.md**

Create `nanobot/templates/prompts/tool_guide.md`:

```markdown
# Tool Selection Guide

Match your INTENT to the right tool. Do not select by name similarity.

| Your intent | Tool | Anti-pattern |
|---|---|---|
| Find files/folders by name or code | `list_dir` | Do NOT use search — it only searches content |
| Search text inside files | `exec` with grep/search | Do NOT use this for name-based lookups |
| Read a known file | `read_file` | Do NOT guess paths — list the directory first |
| Explore unknown structure | `list_dir` first, then `read_file` | Do NOT jump to search without knowing the structure |
| Run a skill command | `exec` | Consult the skill's instructions for which command fits your intent |
| Modify a file | `write_file` or `edit_file` | Always `read_file` first to confirm current content |

## When a Skill Is Loaded

Skills provide specialized commands. But they are ADDITIONS to your
base tools, not REPLACEMENTS. If a skill command fails or returns
nothing, your base tools still work.

Read the skill's decision guide (if present) to choose the right
command for your intent. Do not default to "search" for every
lookup task.
```

- [ ] **Step 3: Create self_check.md**

Create `nanobot/templates/prompts/self_check.md`:

```markdown
## Before Sending Your Response

Self-check:
1. Does every factual claim trace to a tool result in this conversation?
2. If reporting "not found" — did you try at least 2 different approaches?
3. Are you stating anything as fact that you didn't verify with a tool?
4. For memory-sourced claims — are you attributing them? ("Based on our previous conversations...")

If any check fails, take the missing action before responding.
```

- [ ] **Step 4: Update prompts_manifest.json**

Run: `python scripts/check_prompt_manifest.py --update`
This auto-generates the SHA-256 hashes for the new files.

If the script doesn't support `--update`, manually compute hashes:
```bash
cd ../nanobot-phase2-new-components
sha256sum nanobot/templates/prompts/reasoning.md
sha256sum nanobot/templates/prompts/tool_guide.md
sha256sum nanobot/templates/prompts/self_check.md
```
Add the entries to `prompts_manifest.json`.

- [ ] **Step 5: Verify prompt manifest**

Run: `cd ../nanobot-phase2-new-components && python scripts/check_prompt_manifest.py`
Expected: PASS

- [ ] **Step 6: Run make lint && make typecheck**

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add nanobot/templates/prompts/reasoning.md nanobot/templates/prompts/tool_guide.md nanobot/templates/prompts/self_check.md prompts_manifest.json
git commit -m "feat(prompts): add reasoning protocol, tool guide, and self-check templates

Three new prompt templates for the redesigned context architecture:
- reasoning.md: 4-step reasoning protocol before tool selection
- tool_guide.md: purpose-driven tool selection with anti-patterns
- self_check.md: inline verification checklist

Part of Phase 2: agent cognitive core redesign (new components)."
```

---

### Task 4: Create Strategy data model and store

**Files:**
- Create: `nanobot/memory/strategy.py`
- Create: `tests/test_strategy_store.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_strategy_store.py

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from nanobot.memory.strategy import Strategy, StrategyStore


@pytest.fixture
def store(tmp_path):
    """Create a StrategyStore with a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    s = StrategyStore(db_path)
    return s


def _sample_strategy(**overrides) -> Strategy:
    defaults = dict(
        id="test-001",
        domain="obsidian",
        task_type="find_by_name",
        strategy="Use obsidian files folder=X instead of search",
        context="search only matches content, not folder names",
        source="guardrail_recovery",
        confidence=0.5,
        created_at=datetime.now(timezone.utc),
        last_used=datetime.now(timezone.utc),
        use_count=0,
        success_count=0,
    )
    defaults.update(overrides)
    return Strategy(**defaults)


class TestStrategyStore:
    def test_save_and_retrieve(self, store):
        s = _sample_strategy()
        store.save(s)
        results = store.retrieve(domain="obsidian", task_type="find_by_name")
        assert len(results) == 1
        assert results[0].id == "test-001"
        assert results[0].strategy == s.strategy

    def test_retrieve_empty(self, store):
        results = store.retrieve(domain="github", task_type="search")
        assert results == []

    def test_retrieve_by_query(self, store):
        store.save(_sample_strategy(id="s1", domain="obsidian", task_type="find_by_name"))
        store.save(_sample_strategy(id="s2", domain="github", task_type="search_code"))
        results = store.retrieve(domain="obsidian")
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_update_confidence(self, store):
        store.save(_sample_strategy(confidence=0.5))
        store.update_confidence("test-001", 0.7)
        results = store.retrieve(domain="obsidian")
        assert results[0].confidence == pytest.approx(0.7)

    def test_update_usage(self, store):
        store.save(_sample_strategy(use_count=0, success_count=0))
        store.record_usage("test-001", success=True)
        results = store.retrieve(domain="obsidian")
        assert results[0].use_count == 1
        assert results[0].success_count == 1

    def test_record_usage_failure(self, store):
        store.save(_sample_strategy(use_count=0, success_count=0))
        store.record_usage("test-001", success=False)
        results = store.retrieve(domain="obsidian")
        assert results[0].use_count == 1
        assert results[0].success_count == 0

    def test_prune_low_confidence(self, store):
        store.save(_sample_strategy(id="low", confidence=0.05))
        store.save(_sample_strategy(id="high", confidence=0.8))
        pruned = store.prune(min_confidence=0.1)
        assert pruned == 1
        results = store.retrieve(domain="obsidian")
        assert len(results) == 1
        assert results[0].id == "high"

    def test_retrieve_with_limit(self, store):
        for i in range(10):
            store.save(_sample_strategy(id=f"s{i}", confidence=i * 0.1))
        results = store.retrieve(domain="obsidian", limit=3)
        assert len(results) == 3

    def test_retrieve_min_confidence(self, store):
        store.save(_sample_strategy(id="low", confidence=0.1))
        store.save(_sample_strategy(id="high", confidence=0.8))
        results = store.retrieve(domain="obsidian", min_confidence=0.5)
        assert len(results) == 1
        assert results[0].id == "high"

    def test_table_created_on_init(self, store):
        """The strategies table should exist after store creation."""
        import sqlite3
        conn = sqlite3.connect(store._db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategies'"
        )
        assert cursor.fetchone() is not None
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/test_strategy_store.py -v 2>&1 | tail -10`
Expected: ImportError (strategy module doesn't exist yet)

- [ ] **Step 3: Implement strategy.py**

Create `nanobot/memory/strategy.py`:

```python
"""Procedural memory: learned tool-use strategies.

Strategies are extracted from successful guardrail recoveries and user
corrections. They persist across sessions in a SQLite table and are
injected into the system prompt to prevent repeating past failures.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class Strategy:
    """A learned tool-use pattern."""

    id: str
    domain: str
    task_type: str
    strategy: str
    context: str
    source: str
    confidence: float
    created_at: datetime
    last_used: datetime
    use_count: int
    success_count: int


class StrategyStore:
    """CRUD operations for the strategies table in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                task_type TEXT NOT NULL,
                strategy TEXT NOT NULL,
                context TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'guardrail_recovery',
                confidence REAL NOT NULL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_strategies_domain ON strategies(domain)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_strategies_task_type ON strategies(task_type)"
        )
        conn.commit()
        conn.close()

    def save(self, strategy: Strategy) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """INSERT OR REPLACE INTO strategies
            (id, domain, task_type, strategy, context, source, confidence,
             created_at, last_used, use_count, success_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy.id, strategy.domain, strategy.task_type,
                strategy.strategy, strategy.context, strategy.source,
                strategy.confidence,
                strategy.created_at.isoformat(),
                strategy.last_used.isoformat(),
                strategy.use_count, strategy.success_count,
            ),
        )
        conn.commit()
        conn.close()

    def retrieve(
        self,
        domain: str | None = None,
        task_type: str | None = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[Strategy]:
        conn = sqlite3.connect(self._db_path)
        query = "SELECT * FROM strategies WHERE confidence >= ?"
        params: list = [min_confidence]
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        query += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._row_to_strategy(r) for r in rows]

    def update_confidence(self, strategy_id: str, confidence: float) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE strategies SET confidence = ? WHERE id = ?",
            (confidence, strategy_id),
        )
        conn.commit()
        conn.close()

    def record_usage(self, strategy_id: str, *, success: bool) -> None:
        conn = sqlite3.connect(self._db_path)
        if success:
            conn.execute(
                "UPDATE strategies SET use_count = use_count + 1, "
                "success_count = success_count + 1, last_used = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), strategy_id),
            )
        else:
            conn.execute(
                "UPDATE strategies SET use_count = use_count + 1, "
                "last_used = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), strategy_id),
            )
        conn.commit()
        conn.close()

    def prune(self, min_confidence: float = 0.1) -> int:
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "DELETE FROM strategies WHERE confidence < ?",
            (min_confidence,),
        )
        pruned = cursor.rowcount
        conn.commit()
        conn.close()
        return pruned

    @staticmethod
    def _row_to_strategy(row: tuple) -> Strategy:
        return Strategy(
            id=row[0],
            domain=row[1],
            task_type=row[2],
            strategy=row[3],
            context=row[4],
            source=row[5],
            confidence=row[6],
            created_at=datetime.fromisoformat(row[7]),
            last_used=datetime.fromisoformat(row[8]),
            use_count=row[9],
            success_count=row[10],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/test_strategy_store.py -v`
Expected: All tests pass

- [ ] **Step 5: Run make lint && make typecheck**

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/strategy.py tests/test_strategy_store.py
git commit -m "feat(memory): add Strategy model and StrategyStore for procedural memory

Introduces the procedural memory tier: Strategy dataclass for learned
tool-use patterns, and StrategyStore for SQLite CRUD with confidence
tracking, usage recording, and low-confidence pruning.

Part of Phase 2: agent cognitive core redesign (new components)."
```

---

### Task 5: Final validation

- [ ] **Step 1: Run full validation**

Run: `cd ../nanobot-phase2-new-components && rm -rf .mypy_cache && make pre-push 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 2: Verify no existing tests broken**

Run: `cd ../nanobot-phase2-new-components && python -m pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -5`
Expected: All tests pass (existing + new)

- [ ] **Step 3: Verify new components are standalone**

```bash
# Verify no imports from new components in existing code:
grep -rn "turn_guardrails\|from nanobot.memory.strategy" nanobot/agent/ nanobot/context/ nanobot/coordination/ --include="*.py" | grep -v "test\|__pycache__"
```
Expected: No matches (components aren't wired yet)

- [ ] **Step 4: Count new LOC**

```bash
wc -l nanobot/agent/turn_guardrails.py nanobot/memory/strategy.py nanobot/templates/prompts/reasoning.md nanobot/templates/prompts/tool_guide.md nanobot/templates/prompts/self_check.md
```
Expected: ~325 total production LOC

---

## Summary

| Task | Files Created/Modified | Estimated Effort |
|------|----------------------|-----------------|
| 1. ToolAttempt dataclass | 1 modified, 1 test | 10 min |
| 2. Guardrail layer | 1 created, 1 test | 30 min |
| 3. Prompt templates | 3 created, 1 modified | 10 min |
| 4. Strategy model + store | 1 created, 1 test | 20 min |
| 5. Final validation | 0 | 10 min |
| **Total** | **6 created, 2 modified, 4 tests** | **~80 min** |
