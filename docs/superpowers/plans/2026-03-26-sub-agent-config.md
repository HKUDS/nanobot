# SubAgentConfig + MissionManager Refactoring Plan

> **Status:** Complete (PR #81, merged 2026-03-26)

**Goal:** Extract a shared `SubAgentConfig` model that captures sub-agent tool-loop execution parameters, use it to collapse `MissionManager`'s 13-parameter constructor to 7, remove 3 dead fields, and share the config instance with `DelegationDispatcher`.

**Architecture:** Both `DelegationDispatcher` and `MissionManager` run sub-agent tool loops with the same parameters (workspace, model, temperature, max_tokens). A new `SubAgentConfig` Pydantic model in `config/` names this shared concept. `DelegationConfig` wraps `SubAgentConfig` + delegation-specific fields. Both subsystems receive the same instance, constructed once in `build_agent()`.

**Tech Stack:** Python 3.10+, Pydantic, frozen dataclasses, pytest

---

## Key findings from investigation

### 3 dead fields in MissionManager
`brave_api_key`, `exec_config`, and `restrict_to_workspace` were stored on `self` but **never read** by any method. They existed because `build_delegation_tools()` needs them at factory level — they were bundled into MissionManager unnecessarily.

### max_iterations is semantically split
- `AgentConfig.max_iterations` = main agent + delegated sub-agent iteration budget
- `MissionConfig.max_iterations` = background mission agent iteration budget

These are different values, so `max_iterations` stays as a direct parameter on both subsystems, NOT in `SubAgentConfig`.

### DelegationConfig overlap
8 of DelegationConfig's 9 fields appeared in MissionManager's constructor. `role_name` is delegation-specific (caller identity for cycle detection).

## What was done

### Task 1: Create SubAgentConfig model
- Created `nanobot/config/sub_agent.py` with 4 fields: `workspace`, `model`, `temperature`, `max_tokens`
- Added export to `config/__init__.py`

### Task 2: Migrate MissionManager
- Replaced 13 constructor params with `SubAgentConfig` + 3 direct params + `provider`, `bus`, `delegation_tools`
- Removed 3 dead fields entirely
- Updated `agent_factory.py` to construct `SubAgentConfig` and pass it
- Updated 11 test construction sites

### Task 3: Restructure DelegationConfig
- `DelegationConfig` now composes `SubAgentConfig` + delegation-specific fields
- Added `__getattr__` proxy for backward compat (`config.workspace` → `config.sub_agent.workspace`)
- `agent_factory.py` shares the same `SubAgentConfig` instance between both subsystems

### Task 4: Contract test + CI fix
- Added `test_shared_sub_agent_config` verifying both subsystems share the same instance
- Fixed `pip-audit` CI failure: switched to project path mode (`pip-audit . `) to avoid editable package issues

### Results

| Metric | Before | After |
|--------|--------|-------|
| MissionManager constructor params | 13 | 7 |
| Dead fields on MissionManager | 3 | 0 |
| DelegationConfig fields duplicating SubAgentConfig | 4 | 0 (proxied) |
| Shared config instance | No | Yes |
| New files | — | 1 (`config/sub_agent.py`, ~25 LOC) |
