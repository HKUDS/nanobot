---
description: "Prohibited code patterns — violations are bugs"
paths:
  - "nanobot/**/*.py"
  - "tests/**/*.py"
---

# Prohibited Patterns

These are not suggestions — they are errors. Fix immediately if detected.

## Package structure violations

Enforced by `check_imports.py` + `check_structure.py` + `check-placement.sh` hook:
- Import direction violations, catch-all filenames, file count > 15, exports > 12

**Not script-enforced (require judgment):**
- Business logic in `agent/` that belongs in `coordination/`, `memory/`, or `tools/`
- Direct construction of subsystems in `AgentLoop.__init__` (use `agent_factory.py`)
- New flat files in `memory/` that should be in a subdirectory
- Tool implementations at `tools/` level instead of `tools/builtin/`

## Code quality violations

Enforced by `check_structure.py`: crash-barrier comments, file size > 500 LOC.

**Not script-enforced:**
- Magic numbers outside of config schema or named constants
- Circular imports resolved by `TYPE_CHECKING` guards that mask a real boundary violation

## Wiring violations

- Subsystem construction outside `agent_factory.py` (grep for `SomeSubsystem(` in
  orchestration modules)
- Post-construction wiring that reaches into private attributes of another subsystem.
  If a component needs a dependency, pass it at construction time. If a circular
  dependency prevents this, use a lazy callback (`lambda: self.dependency`) to break
  the cycle — never leave a field as None with defensive null-checks.
  See `tests/contract/test_memory_wiring.py` for the pattern.
- Sharing mutable collections (dicts, lists, sets) across multiple components without
  a documented synchronization strategy. Either pass immutable snapshots (replace
  atomically, not mutate in-place), or document the sharing contract with a comment
  at each receiver: `# shared-ref: <what>, <mutation contract>`
- Re-export chains (A re-exports from B re-exports from C) — flatten to direct imports
- Concrete class imports across package boundaries where a Protocol should be used
- Extracted components caching mutable state that the parent class modifies at
  runtime (e.g., fields updated by role switching, configuration reloads, or
  per-turn overrides). If a field on `AgentLoop` can change after construction,
  every extracted component that reads that field must have a propagation path
  (per-call parameters, shared reference, or `TurnState` fields) — not a stale
  construction-time copy. See `tests/contract/test_role_propagation.py` for the
  pattern.
- Processing steps (context building, orchestration) implemented at the
  entry-point level (`AgentLoop.run()`, `process_direct()`) rather than inside
  `MessageProcessor._process_message()`. Entry points must be thin shells that
  delegate to the processor.
- Domain logic in the loop — the loop is a dumb tool-use driver. Behavioral fixes
  go through extension points (guardrails, context contributors, prompt templates),
  not by adding conditionals to `TurnRunner`.

## Growth violations

Enforced by `check_structure.py` — file count, LOC, and export limits are hard gates.
The rule: extract BEFORE adding, not after. No TODOs for future extraction.
