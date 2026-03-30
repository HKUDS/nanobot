# Plan: Remove Delegation Subsystem

> Date: 2026-03-29
> Decision: Delegation spawns generic sub-agents with no functional specialization.
> The coordinator (role routing) was deleted in ADR-011 but delegation wasn't cleaned up.
> Every delegation attempt crashes with NanobotError. Remove entirely.

## Scope

### Delete 3 source files (~1,100 LOC)

- `nanobot/coordination/delegation.py` (588 lines)
- `nanobot/coordination/delegation_contract.py` (232 lines)
- `nanobot/tools/builtin/delegate.py` (280 lines)

### Delete 8 test files

- `tests/test_delegate.py`
- `tests/test_delegation_dispatcher.py`
- `tests/test_delegation_contract.py`
- `tests/test_delegation_security.py`
- `tests/test_delegation_validation.py`
- `tests/test_delegation_verification.py`
- `tests/test_parallel_delegation.py`
- `tests/integration/test_delegation_child_agent.py`

### Modify 6 source files (remove delegation wiring)

| File | What to remove |
|---|---|
| `agent/agent_factory.py` | DelegationDispatcher construction, DelegationConfig, delegation_tools wiring |
| `agent/agent_components.py` | `dispatcher` field from `_Subsystems` and `_ProcessorServices` |
| `agent/loop.py` | `self._dispatcher`, MCP tools assignment to dispatcher, `_delegation_stack` |
| `agent/message_processor.py` | `self._dispatcher` |
| `agent/turn_context.py` | Dispatcher parameter, scratchpad/trace wiring to dispatcher |
| `tools/setup.py` | `build_delegation_tools()`, DelegateTool/DelegateParallelTool registration |

### Modify ~8 test files (remove delegation references)

- `test_agent_loop.py` — delegation depth/cycle test cases (lines 690-746)
- `test_loop_helper_paths.py` — delegation contract injection (lines 8-9, 119)
- `test_observability_plumbing.py` — dispatcher wiring in 3 places (lines 785, 846, 902)
- `test_coverage_push_wave6.py` — ancestry ContextVar test (lines 11, 351)
- `test_capability_availability.py` — delegate tool availability (line 12)
- `test_pass2_smoke.py` — delegate tool smoke test (line 29)
- `test_sub_agent_config.py` — DelegationConfig reference (line 52)
- `test_token_reduction.py` — scratchpad injection limit helpers (lines 70, 80)

### Related decisions

| File | Action | Reason |
|---|---|---|
| `coordination/scratchpad.py` | **Keep** | Used by missions independently |
| `tools/builtin/scratchpad.py` | **Keep** | Agent can read/write scratchpad directly |
| `coordination/mission.py` | **Modify** | Remove `delegation_tools` parameter (missions can't delegate) |
| `agent/failure.py` | **Audit** | `_CycleError` may be removable if only delegation used it |

### Documentation to update

- `CLAUDE.md` — remove delegation from coordination description
- `.claude/rules/architecture.md` — remove delegation references, data flow diagram
- `.claude/rules/architecture-constraints.md` — remove delegation examples
- ADR-011 — add note that delegation was subsequently removed (historical record)

## Constants and types removed

- `DelegateTool`, `DelegateParallelTool` classes
- `DelegationResult` dataclass
- `DelegationConfig` dataclass
- `DelegationDispatcher` class
- `DispatchFn`, `AvailableRolesFn` type aliases
- `_CycleError` exception (audit if mission still uses)
- `_delegation_ancestry` ContextVar
- `MAX_DELEGATION_DEPTH` constant
- `get_delegation_depth()` function
- `_SCRATCHPAD_INJECTION_LIMIT` constant
- `build_delegation_contract()` and helpers

## Build sequence

1. Create worktree `fix/remove-delegation`
2. Delete 3 source files + 8 test files
3. Clean imports in 6 source files
4. Clean references in ~8 test files
5. Clean `mission.py` delegation_tools parameter
6. Audit `_CycleError` — remove if delegation-only
7. `make lint && make typecheck`
8. `make check` — structural validation
9. Update CLAUDE.md and architecture docs
10. `make pre-push` — full CI
11. Code review subagent
12. Commit, push, PR

## Risk assessment

- **Low risk** — delegation is already broken (every call crashes)
- **Coverage impact** — deleting ~1,100 source lines and their tests changes the ratio
- **Mission impact** — missions accept `delegation_tools` but delegation is broken anyway

## Post-deletion checklist (per change-protocol.md)

Grep for THREE patterns after deletion:
1. `grep -rn "from nanobot.coordination.delegation" nanobot/ tests/`
2. `grep -rn "\bDelegationDispatcher\b" nanobot/ tests/ --include="*.py"`
3. `grep -rn "\.dispatch\b" nanobot/ tests/ --include="*.py"` (filter false positives)

Clear mypy cache and re-run typecheck.
