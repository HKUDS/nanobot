# Agent Factory Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract all subsystem construction from `AgentLoop.__init__` into a `build_agent()` factory function in `agent_factory.py`.

**Architecture:** A new `agent_factory.py` module contains a `_AgentComponents` dataclass and a `build_agent()` factory function. The factory constructs all 15+ subsystems, packs them into `_AgentComponents`, and passes them to a slimmed-down `AgentLoop.__init__` that only stores references. Post-construction wiring (TurnRoleManager, token source, span module) happens after `AgentLoop` is created.

**Tech Stack:** Python 3.10+, Pydantic, dataclasses, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-agent-factory-extraction-design.md`

**Critical ordering note:** Tasks are ordered so that every committed state passes `make check`. The factory is created first (Task 1), then all callers are migrated to use it (Tasks 2-3), and only then is `AgentLoop.__init__` slimmed (Task 4). This avoids any intermediate broken state.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `nanobot/agent/agent_factory.py` | `_AgentComponents` dataclass, `build_agent()`, `_build_rollout_overrides()`, `_build_tools()`, `_wire_memory()` |
| Modify | `nanobot/agent/loop.py` | Slim `__init__` to accept `_AgentComponents`; remove `_build_tools`, `_wire_memory`, `_register_default_tools`; keep all runtime methods |
| Modify | `nanobot/agent/__init__.py` | Add `build_agent` to exports |
| Modify | `nanobot/cli/_shared.py:181-189` | Change `AgentLoop(...)` → `build_agent(...)` |
| Modify | `nanobot/cli/agent.py:190` | Change `AgentLoop(...)` → `build_agent(...)` |
| Modify | `nanobot/cli/gateway.py:72,327` | Change `AgentLoop(...)` → `build_agent(...)` |
| Modify | `nanobot/cli/routing.py:316` | Change `AgentLoop(...)` → `build_agent(...)` |
| Modify | `nanobot/cli/cron.py:199` | Change `AgentLoop(...)` → `build_agent(...)` |
| Modify | `tests/helpers.py:92-100` | Update `_make_loop()` to use `build_agent()` |
| Modify | `tests/test_loop_helper_paths.py:202` | Update `_make_loop_via_init()` to use `build_agent()` |
| Modify | `tests/test_capability_wiring.py` | Update its `_make_loop()` to use `build_agent()` |
| Modify | `tests/test_commands_gateway_agent.py` | Update patch targets from `AgentLoop` to `build_agent` |
| Modify | `tests/test_commands_routing_cron.py` | Update patch targets from `AgentLoop` to `build_agent` |
| Create | `tests/test_agent_factory.py` | Tests for `build_agent()` |

---

### Task 1: Create `agent_factory.py` with `_AgentComponents` and `build_agent()`

**Files:**
- Create: `nanobot/agent/agent_factory.py`

At this stage, `build_agent()` creates all subsystems and ALSO calls the existing `AgentLoop.__init__` (which still works the old way). This is a parallel path — both the factory and the old constructor work. We migrate callers next, then slim the constructor last.

- [ ] **Step 1: Create `agent_factory.py` with full implementation**

Create the file with:
1. `_build_rollout_overrides(config)` — extract the ~30-line dict from `loop.py:185-213`
2. `_build_tools(...)` — standalone version of `loop.py:339-394`
3. `_wire_memory(...)` — standalone version of `loop.py:395-428`
4. `_AgentComponents` dataclass with all fields from the spec. **Important:** `role_manager` must be typed `TurnRoleManager | None` (not `TurnRoleManager`) because it is `None` during intermediate construction before post-construction wiring.
5. `build_agent()` that constructs everything and returns `AgentLoop`

**Initial `build_agent()` implementation:** For this task, the factory creates all subsystems but still calls the OLD `AgentLoop.__init__` (passing the original keyword arguments, not `_AgentComponents`). This means the factory works immediately without requiring `loop.py` changes. We'll switch to the components-based `__init__` in Task 4.

Construction order inside `build_agent()`:
1. Resolve model/temperature/max_iterations from role_config + config + provider
2. Build rollout overrides dict via `_build_rollout_overrides(config)`
3. Return `AgentLoop(bus=bus, provider=provider, config=config, ...)` with all the original keyword args

This is a stepping stone — the full factory construction (bypassing `AgentLoop.__init__`) happens in Task 4 when we slim the constructor.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "from nanobot.agent.agent_factory import build_agent, _AgentComponents"`
Expected: No ImportError

- [ ] **Step 3: Run existing tests to verify nothing broke**

Run: `python -m pytest tests/test_agent_loop.py -x -q`
Expected: All pass (factory delegates to old __init__)

- [ ] **Step 4: Commit**

```bash
git add nanobot/agent/agent_factory.py
git commit -m "refactor: create agent_factory.py with build_agent (delegates to old __init__)"
```

---

### Task 2: Update CLI callers to use `build_agent()`

**Files:**
- Modify: `nanobot/cli/_shared.py:181-189`
- Modify: `nanobot/cli/agent.py:190`
- Modify: `nanobot/cli/gateway.py:72,327`
- Modify: `nanobot/cli/routing.py:316`
- Modify: `nanobot/cli/cron.py:199`

Since `build_agent()` currently delegates to the old `AgentLoop.__init__`, this migration is safe and transparent.

- [ ] **Step 1: Update `_shared.py`**

Change:
```python
# Old (line 181)
from nanobot.agent.loop import AgentLoop as _AgentLoop
# ...
return _AgentLoop(bus=bus, provider=provider, ...)
```
To:
```python
from nanobot.agent.agent_factory import build_agent
# ...
return build_agent(bus=bus, provider=provider, ...)
```

Parameters are identical — mechanical change.

- [ ] **Step 2: Update remaining CLI files**

For each of `agent.py`, `gateway.py`, `routing.py`, `cron.py`: check if it constructs `AgentLoop` directly or calls `_shared._make_agent_loop()`.

If it constructs directly, change import + constructor call:
```python
# Old
from nanobot.agent.loop import AgentLoop
agent = AgentLoop(bus=bus, provider=provider, config=config, ...)

# New
from nanobot.agent.agent_factory import build_agent
agent = build_agent(bus=bus, provider=provider, config=config, ...)
```

If it calls `_shared._make_agent_loop()`, no change needed.

- [ ] **Step 3: Run tests to verify nothing broke**

Run: `python -m pytest tests/ -x -q`
Expected: All pass (factory still delegates to old __init__)

- [ ] **Step 4: Commit**

```bash
git add nanobot/cli/_shared.py nanobot/cli/agent.py nanobot/cli/gateway.py nanobot/cli/routing.py nanobot/cli/cron.py
git commit -m "refactor: migrate CLI callers to build_agent()"
```

---

### Task 3: Update test helpers and patch targets

**Files:**
- Modify: `tests/helpers.py:92-100`
- Modify: `tests/test_loop_helper_paths.py:202`
- Modify: `tests/test_capability_wiring.py` (if it has its own `_make_loop()`)
- Modify: `tests/test_commands_gateway_agent.py`
- Modify: `tests/test_commands_routing_cron.py`

- [ ] **Step 1: Update `tests/helpers.py`**

Update `_make_loop()` (line 92) to use `build_agent()`:
```python
from nanobot.agent.agent_factory import build_agent

def _make_loop(provider=None, config=None, bus=None, tool_registry=None):
    # ... existing provider/config/bus setup ...
    return build_agent(
        bus=bus, provider=provider, config=config,
        tool_registry=tool_registry,
    )
```

`make_agent_loop()` at line 99 calls `_make_loop()` — it's fixed transitively.

- [ ] **Step 2: Update `tests/test_loop_helper_paths.py`**

This file has `_make_loop_via_init()` at line 202 that constructs `AgentLoop(...)` directly. Update it to call `build_agent()`:
```python
from nanobot.agent.agent_factory import build_agent

def _make_loop_via_init(tmp_path, provider, tool_registry=None):
    # ... existing setup ...
    return build_agent(bus=bus, provider=provider, config=config, tool_registry=tool_registry)
```

- [ ] **Step 3: Update `tests/test_capability_wiring.py`**

Check if this file has its own `_make_loop()` that constructs `AgentLoop` directly. If so, update the same way.

- [ ] **Step 4: Update patch targets in command tests**

The CLI callers now import `build_agent` from specific modules. Patch targets must match the import location:

**`tests/test_commands_gateway_agent.py`:**
- Patches for `gateway.py` tests: change `"nanobot.agent.loop.AgentLoop"` → `"nanobot.cli.gateway.build_agent"` (if gateway.py imports directly) or `"nanobot.cli._shared.build_agent"` (if gateway.py uses `_make_agent_loop`)
- Patches for `agent.py` tests: change to `"nanobot.cli.agent.build_agent"` (if agent.py imports directly) or `"nanobot.cli._shared.build_agent"`

**`tests/test_commands_routing_cron.py`:**
- Patches for `cron.py` tests: change to `"nanobot.cli.cron.build_agent"` or `"nanobot.cli._shared.build_agent"`

**To determine the correct target:** check each CLI file from Task 2. If `gateway.py` calls `_shared._make_agent_loop()`, then the patch target is `"nanobot.cli._shared.build_agent"`. If `gateway.py` calls `build_agent()` directly, the target is `"nanobot.cli.gateway.build_agent"`.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass (except pre-existing `test_timeout`)

- [ ] **Step 6: Commit**

```bash
git add tests/helpers.py tests/test_loop_helper_paths.py tests/test_capability_wiring.py tests/test_commands_gateway_agent.py tests/test_commands_routing_cron.py
git commit -m "refactor: migrate test helpers and patch targets to build_agent()"
```

---

### Task 4: Slim `AgentLoop.__init__` and complete the factory

**Files:**
- Modify: `nanobot/agent/agent_factory.py` — make `build_agent()` construct subsystems directly instead of delegating to old `__init__`
- Modify: `nanobot/agent/loop.py:145-456` — replace `__init__` with components-based version

Now that ALL callers (CLI + tests) use `build_agent()`, we can safely change `AgentLoop.__init__` without breaking anything.

- [ ] **Step 1: Update `build_agent()` to full factory mode**

Replace the delegating `return AgentLoop(bus=bus, ...)` with the full construction sequence:
1. Resolve model/temperature/max_iterations
2. `_build_rollout_overrides(config)`
3. Construct MemoryStore, ContextBuilder, SessionManager
4. `_build_tools(...)` → ToolExecutor, CapabilityRegistry, MissionManager, ToolResultCache
5. `_wire_memory(...)` → ConsolidationOrchestrator
6. Construct DelegationDispatcher, DelegationAdvisor, StreamingLLMCaller, AnswerVerifier
7. Construct TurnOrchestrator, MessageProcessor (with `role_manager=None`)
8. Pack `_AgentComponents` (role_manager=None)
9. `loop = AgentLoop(components=components)`
10. Post-construction wiring:
    - `role_manager = TurnRoleManager(loop)`
    - `loop._role_manager = role_manager`
    - `loop._processor._role_manager = role_manager`
    - `loop._processor._token_source = loop`
    - `loop._processor._span_module = sys.modules["nanobot.agent.loop"]`
11. Return loop

- [ ] **Step 2: Replace `AgentLoop.__init__` with components-based version**

Replace the entire `__init__` (lines 145-337) with the slim version from the spec. Add import at top of `loop.py`:
```python
from nanobot.agent.agent_factory import _AgentComponents
```

The new `__init__` accepts `*, components: _AgentComponents` and only stores references + initializes runtime state. Include `self._register_handlers()` at the end.

- [ ] **Step 3: Remove moved methods from `loop.py`**

Delete:
- `_build_tools()` (lines 339-394)
- `_wire_memory()` (lines 395-428)
- `_register_default_tools()` (lines 438-456)

Keep `_register_handlers()` — it stays in `loop.py`.

- [ ] **Step 4: Clean up `loop.py` imports**

Remove imports only needed by the old constructor/build methods. Keep:
- Imports for runtime methods (`run`, `stop`, `process_direct`, `handle_reaction`, `_connect_mcp`, `_ensure_coordinator`, etc.)
- All backward-compat re-exports (lines 91-105)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/agent_factory.py nanobot/agent/loop.py
git commit -m "refactor: slim AgentLoop.__init__ to accept _AgentComponents"
```

---

### Task 5: Add `build_agent` to `__init__.py` exports

**Files:**
- Modify: `nanobot/agent/__init__.py`

- [ ] **Step 1: Add import and export**

Add to imports:
```python
from nanobot.agent.agent_factory import build_agent
```

Add `"build_agent"` to `__all__` (alphabetical order, after `"AnswerVerifier"`).

`_AgentComponents` is NOT added to `__all__` — tests import it directly from `nanobot.agent.agent_factory`.

- [ ] **Step 2: Commit**

```bash
git add nanobot/agent/__init__.py
git commit -m "refactor: export build_agent from agent package"
```

---

### Task 6: Write factory tests

**Files:**
- Create: `tests/test_agent_factory.py`

- [ ] **Step 1: Write tests for `build_agent()`**

Test cases:
1. **Default construction** — `build_agent(bus, provider, config)` returns an `AgentLoop` with all subsystems wired
2. **Injected tool registry** — `build_agent(..., tool_registry=custom_reg)` uses the provided registry
3. **Memory disabled** — config with `memory_enabled=False` sets memory token budgets to 0
4. **Delegation disabled** — config with `delegation_enabled=False` does not register delegate tools
5. **Role config override** — `build_agent(..., role_config=role)` applies model/temperature/max_iterations from role
6. **Post-construction wiring** — verify `loop._role_manager` is a real `TurnRoleManager` (not None), `loop._processor._token_source is loop`

Use the existing `ScriptedProvider` and config helpers from `tests/helpers.py`.

- [ ] **Step 2: Run new tests**

Run: `python -m pytest tests/test_agent_factory.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_factory.py
git commit -m "test: add unit tests for build_agent factory"
```

---

### Task 7: Final verification

**Files:**
- Verify: all changed files

- [ ] **Step 1: Run full validation**

```bash
make lint && make typecheck
```

Fix any lint or type errors.

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -x -q
```

Expected: All pass (except pre-existing `test_timeout`).

- [ ] **Step 3: Verify import count reduction**

```bash
grep "^from nanobot\|^import nanobot" nanobot/agent/loop.py | wc -l
```

Expected: ~12 or fewer (down from ~28).

- [ ] **Step 4: Verify no construction in __init__**

```bash
grep -n "MemoryStore\|ContextBuilder\|ToolExecutor\|DelegationDispatcher\|TurnOrchestrator\|MessageProcessor\|MissionManager\|StreamingLLMCaller\|AnswerVerifier\|CapabilityRegistry\|ConsolidationOrchestrator\|ToolResultCache" nanobot/agent/loop.py
```

Expected: Only type annotations, attribute access, and backward-compat re-exports — no constructor calls (`(...)`).

- [ ] **Step 5: Commit if any fixes were needed**

```bash
git add -A
git commit -m "refactor: final cleanup for agent factory extraction"
```
