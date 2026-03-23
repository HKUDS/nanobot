# Delegation Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract task type taxonomy and contract construction from `delegation.py` into `task_types.py` and `delegation_contract.py`, reducing `delegation.py` from 1,002 to ~550 lines.

**Architecture:** Two new modules extracted from `DelegationDispatcher`. `task_types.py` has zero agent/ dependencies (pure data + regex). `delegation_contract.py` depends only on `task_types` and `prompt_loader`. Instance methods become module-level functions with explicit parameters. Backward-compat re-exports and static-method wrappers preserve all existing call patterns.

**Tech Stack:** Python 3.10+, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-delegation-decomposition-design.md`

**Critical ordering note:** Tasks are ordered so every committed state passes `make check`. New modules are created first (Tasks 1-2), then callers are updated (Task 3), then old code is removed (Task 4). Backward-compat re-exports ensure no intermediate breakage.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `nanobot/agent/task_types.py` | `TASK_TYPES`, `classify_task_type()`, `has_parallel_structure()` |
| Create | `nanobot/agent/delegation_contract.py` | `build_delegation_contract()`, context helpers, `_cap_scratchpad_for_injection()` |
| Modify | `nanobot/agent/delegation.py` | Remove extracted code, add backward-compat re-exports and static-method wrappers |
| Modify | `nanobot/agent/mission.py:25` | Change `TASK_TYPES` import from `delegation` to `task_types` |
| Modify | `nanobot/agent/turn_orchestrator.py:774` | Change `has_parallel_structure` to direct import from `task_types` |
| Modify | `nanobot/agent/delegation_advisor.py` | Change `has_parallel_structure` to direct import from `task_types` |
| Create | `tests/test_task_types.py` | Tests for classify + parallel structure |
| Create | `tests/test_delegation_contract.py` | Tests for contract assembly + context helpers |

---

### Task 1: Create `task_types.py`

**Files:**
- Create: `nanobot/agent/task_types.py`

- [ ] **Step 1: Create `task_types.py` with extracted code**

Move from `delegation.py`:
- `TASK_TYPES` dict (lines 88-170) — copy verbatim
- `classify_task_type(role: str, task: str) -> str` (lines 490-597) — was `@staticmethod` on `DelegationDispatcher`, becomes module-level function. Copy the function body verbatim, only removing `self` references (there are none — it's already a static method).
- `has_parallel_structure(text: str) -> bool` (lines 600-622) — same treatment

The file should start with:
```python
"""Task type taxonomy for delegation and mission classification.

Pure data + keyword matching — no dependencies on the delegation dispatch layer.
"""
from __future__ import annotations

import re
from typing import Any
```

Only import needed: `re` (stdlib) for `has_parallel_structure`. No agent/ imports.

Note: `classify_task_type` currently takes `role: str` (not `AgentRoleConfig`). Keep it as `str`.

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd /c/Users/C95071414/Documents/nanobot-refactor/arch-refactoring
python -c "from nanobot.agent.task_types import TASK_TYPES, classify_task_type, has_parallel_structure; print(len(TASK_TYPES), 'task types')"
```

Expected: `7 task types`

- [ ] **Step 3: Commit**

```bash
git add nanobot/agent/task_types.py
git commit -m "refactor: extract task_types.py from delegation.py"
```

---

### Task 2: Create `delegation_contract.py`

**Files:**
- Create: `nanobot/agent/delegation_contract.py`

- [ ] **Step 1: Create `delegation_contract.py` with extracted code**

Move from `delegation.py`:
- `_SCRATCHPAD_INJECTION_LIMIT = 4_000` (line 82)
- `_cap_scratchpad_for_injection(content, limit)` (lines 173-180)
- `gather_recent_tool_results(active_messages, max_results, max_chars)` (lines 378-414) — was instance method reading `self.active_messages`. Becomes function with `active_messages: list[dict]` as first param.
- `extract_plan_text(active_messages)` (lines 416-433) — same treatment
- `extract_user_request(active_messages)` (lines 435-444) — same treatment
- `build_execution_context(workspace, task_type)` (lines 446-469) — was instance method reading `self.workspace`. Becomes function with `workspace: Path` param.
- `build_parallel_work_summary(scratchpad, role)` (lines 471-483) — was instance method reading `self.scratchpad`. Becomes function with explicit `scratchpad` param.
- `build_delegation_contract(role, task, context, task_type, workspace, user_request, plan_text, recent_results, execution_context, parallel_summary, scratchpad_content)` (lines 628-696) — was instance method calling the other helpers via `self.*`. Becomes module-level function. The caller in `delegation.py` will call the helpers first and pass results as arguments.

**Important transformation:** The current `build_delegation_contract` calls `self.extract_user_request()`, `self.extract_plan_text()`, `self.gather_recent_tool_results()`, `self.build_execution_context(task_type)`, and reads `self.workspace`. After extraction, the function takes pre-computed results as parameters. The caller (`DelegationDispatcher.execute_delegated_agent`) calls the helpers first and passes the results.

Alternatively (simpler): `build_delegation_contract` takes `workspace`, `active_messages`, `scratchpad`, and calls the helpers internally. This avoids changing the caller's flow. Check which approach matches the actual code more naturally by reading `delegation.py:628-696` and `delegation.py:841-1002`.

The file imports:
```python
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.prompt_loader import prompts
from nanobot.agent.task_types import TASK_TYPES
from nanobot.agent.tracing import bind_trace

if TYPE_CHECKING:
    from nanobot.agent.scratchpad import Scratchpad
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
python -c "from nanobot.agent.delegation_contract import build_delegation_contract, _cap_scratchpad_for_injection; print('OK')"
```

Expected: OK

- [ ] **Step 3: Commit**

```bash
git add nanobot/agent/delegation_contract.py
git commit -m "refactor: extract delegation_contract.py from delegation.py"
```

---

### Task 3: Update callers to use new modules directly

**Files:**
- Modify: `nanobot/agent/mission.py:25`
- Modify: `nanobot/agent/turn_orchestrator.py`
- Modify: `nanobot/agent/delegation_advisor.py`

- [ ] **Step 1: Update `mission.py`**

Change:
```python
# Old
from nanobot.agent.delegation import TASK_TYPES
# New
from nanobot.agent.task_types import TASK_TYPES
```

- [ ] **Step 2: Update `turn_orchestrator.py`**

Find where it calls `DelegationDispatcher.has_parallel_structure(...)`. Change to:
```python
from nanobot.agent.task_types import has_parallel_structure
# ...
has_parallel_structure(state.user_text)  # instead of DelegationDispatcher.has_parallel_structure(...)
```

- [ ] **Step 3: Update `delegation_advisor.py`**

Find where it calls `DelegationDispatcher.has_parallel_structure(...)` or `self._dispatcher.has_parallel_structure(...)`. Change to direct import from `task_types`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/mission.py nanobot/agent/turn_orchestrator.py nanobot/agent/delegation_advisor.py
git commit -m "refactor: update callers to import from task_types directly"
```

---

### Task 4: Remove extracted code from `delegation.py` and add backward-compat

**Files:**
- Modify: `nanobot/agent/delegation.py`

- [ ] **Step 1: Remove extracted code from `delegation.py`**

Remove:
- `TASK_TYPES` dict (lines 88-170)
- `_SCRATCHPAD_INJECTION_LIMIT` constant (line 82)
- `_cap_scratchpad_for_injection()` function (lines 173-180)
- `classify_task_type()` static method body (lines 490-597) — keep as thin wrapper
- `has_parallel_structure()` static method body (lines 600-622) — keep as thin wrapper
- `build_delegation_contract()` method (lines 628-696) — remove entirely, callers updated in-place
- `gather_recent_tool_results()` method (lines 378-414) — remove
- `extract_plan_text()` method (lines 416-433) — remove
- `extract_user_request()` method (lines 435-444) — remove
- `build_execution_context()` method (lines 446-469) — remove
- `build_parallel_work_summary()` method (lines 471-483) — remove

- [ ] **Step 2: Add imports from new modules**

```python
from nanobot.agent.task_types import TASK_TYPES, classify_task_type, has_parallel_structure
from nanobot.agent.delegation_contract import (
    _SCRATCHPAD_INJECTION_LIMIT,
    _cap_scratchpad_for_injection,
    build_delegation_contract,
    build_execution_context,
    build_parallel_work_summary,
    extract_plan_text,
    extract_user_request,
    gather_recent_tool_results,
)
```

These serve double duty: backward-compat re-exports AND local use within `delegation.py`.

- [ ] **Step 3: Add static-method wrappers on DelegationDispatcher**

```python
@staticmethod
def classify_task_type(role: str, task: str) -> str:
    return classify_task_type(role, task)

@staticmethod
def has_parallel_structure(text: str) -> bool:
    return has_parallel_structure(text)
```

- [ ] **Step 4: Update `dispatch()` and `execute_delegated_agent()` to call module functions**

Where these methods currently call `self.build_delegation_contract(...)`, `self.gather_recent_tool_results(...)`, etc., change to call the imported module-level functions, passing `self.active_messages`, `self.workspace`, `self.scratchpad` as explicit arguments.

Read the actual method bodies to determine exact changes needed. The key pattern:
```python
# Old
results = self.gather_recent_tool_results()
# New
results = gather_recent_tool_results(self.active_messages)
```

- [ ] **Step 5: Clean up unused imports**

Remove any imports that were only needed by the extracted code (e.g., `re` if only used by `has_parallel_structure`).

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: All pass

- [ ] **Step 7: Verify line count**

```bash
wc -l nanobot/agent/delegation.py
```

Expected: Under 600 lines

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/delegation.py
git commit -m "refactor: remove extracted code from delegation.py, add backward-compat"
```

---

### Task 5: Write tests for new modules

**Files:**
- Create: `tests/test_task_types.py`
- Create: `tests/test_delegation_contract.py`

- [ ] **Step 1: Write `tests/test_task_types.py`**

Test cases:
1. `test_task_types_keys` — verify TASK_TYPES has all 7 expected keys
2. `test_classify_code_task` — classify a code-related task
3. `test_classify_web_research` — classify a web research task
4. `test_classify_general_fallback` — unmatched task returns "general"
5. `test_has_parallel_structure_numbered` — "1. X 2. Y 3. Z" returns True
6. `test_has_parallel_structure_none` — plain text returns False
7. `test_classify_task_type_role_override` — specific role affects classification

- [ ] **Step 2: Write `tests/test_delegation_contract.py`**

Test cases:
1. `test_cap_scratchpad_under_limit` — content under limit passes through
2. `test_cap_scratchpad_over_limit` — content truncated with continuation hint
3. `test_extract_user_request_empty` — empty messages returns empty string
4. `test_extract_user_request_found` — finds first user message
5. `test_gather_recent_tool_results_empty` — no tool results returns empty string
6. `test_build_execution_context` — returns workspace listing for a tmp_path

- [ ] **Step 3: Run new tests**

```bash
python -m pytest tests/test_task_types.py tests/test_delegation_contract.py -v
```

Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_task_types.py tests/test_delegation_contract.py
git commit -m "test: add tests for task_types and delegation_contract modules"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full validation**

```bash
make lint
python -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 2: Verify no reverse dependencies**

```bash
grep "from nanobot.agent.delegation" nanobot/agent/task_types.py
grep "from nanobot.agent.delegation" nanobot/agent/delegation_contract.py
```

Both should return empty — no reverse dependencies.

- [ ] **Step 3: Verify delegation.py size**

```bash
wc -l nanobot/agent/delegation.py nanobot/agent/task_types.py nanobot/agent/delegation_contract.py
```

Expected: delegation.py < 600, task_types.py ~213, delegation_contract.py ~173

- [ ] **Step 4: Commit if any fixes needed**

```bash
git add -A
git commit -m "refactor: final cleanup for delegation decomposition"
```
