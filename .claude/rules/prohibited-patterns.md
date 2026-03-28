---
description: "Prohibited code patterns — violations are bugs"
globs:
  - "nanobot/**/*.py"
  - "tests/**/*.py"
---

# Prohibited Patterns

These are not suggestions — they are errors. Fix immediately if detected.

## Package structure violations

- Business logic in `agent/` that belongs in `coordination/`, `memory/`, or `tools/`
- Direct construction of subsystems in `AgentLoop.__init__` (use `agent_factory.py`)
- Import direction violations — outer packages importing from inner ones
- New flat files in `memory/` that should be in a subdirectory
- Tool implementations at `tools/` level instead of `tools/builtin/`
- Catch-all modules (`utils.py`, `helpers.py`, `common.py`) with mixed ownership
- A package exceeding 15 top-level `.py` files without planned extraction
- An `__init__.py` with more than 12 `__all__` exports

## Code quality violations

- Magic numbers outside of config schema or named constants
- `except Exception` without `# crash-barrier: <reason>` comment
- Circular imports resolved by `TYPE_CHECKING` guards that mask a real boundary violation
- Files exceeding 500 LOC without `# size-exception: <reason>`

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

- Adding a file to a package at its file-count limit without extracting first
- Adding code that pushes a file past 500 LOC without extracting first
- Adding an `__init__.py` export that pushes past 12 without extracting first
