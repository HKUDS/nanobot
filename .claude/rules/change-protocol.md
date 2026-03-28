# Change Protocol

## Before implementing any change (including trivial ones)

**For every change — even a single new file or method:**
1. Name the owning package and why.
2. Confirm the file placement passes the Placement Gate.
3. Confirm the file size stays within limits.
4. Confirm no import boundary violations.

**For non-trivial changes (new features, refactors, multi-file changes), also:**
5. List files to create or modify.
6. Identify any risks to boundaries or coupling.
7. Do not start coding until placement is clear. If placement is ambiguous, resolve the
   design question first.

## Before any structural refactoring (extracting, promoting, moving packages)

**Before writing an extraction plan:**
1. **Trace call paths** that cross the proposed extraction boundary. For each call path,
   document: caller -> callee, and what contract the caller depends on (return type,
   side effects, state mutations).
2. **Identify shared methods** — methods that both sides of the boundary will need after
   extraction. These must be placed once, in the package that owns the concept.
3. **Identify post-construction wiring** — patterns where subsystem A reaches into
   subsystem B's internals after construction. These must be surfaced and resolved
   (via dependency injection or Protocol interfaces) before extraction, not after.
4. **Check for re-export chains** — if module A re-exports from module B, and module B
   re-exports from module C, the chain will break during extraction. Flatten to direct
   imports first.
5. **Verify Protocol surface area** — if extraction requires a new Protocol interface,
   define it and verify that the concrete implementation satisfies it *before* moving files.
6. **Check mutable state propagation** — if the extracted component receives any
   field at construction time that the parent class can modify at runtime (model,
   temperature, role_name, etc.), verify the extracted component has a propagation
   path for runtime updates — not a stale copy. Add an integration test that
   modifies the field on the parent, runs a turn, and asserts the component used
   the updated value. See `tests/contract/test_role_propagation.py` for the pattern.

## After completing changes

Confirm:
- No logic leaked into the wrong package
- No new imports violating boundary rules (`make import-check`)
- Package growth limits still within thresholds
- Tests cover the new behavior
- `make lint && make typecheck` passes
- Documentation updated if public API changed
- If a component writes data consumed by another component, verify the data contract
  with a test (both writer and reader agree on required keys, types, defaults)
- If implementation deviates from the spec, update the spec IMMEDIATELY in the same
  commit. Add a `## Deviations` section. Stale specs mislead future sessions.

## After deleting any module

Grep for THREE patterns (not just imports):
1. Import path: `grep -rn "from nanobot.X.deleted_module" nanobot/ tests/`
2. Class name: `grep -rn "\bDeletedClass\b" nanobot/ tests/ --include="*.py"`
3. Attribute: `grep -rn "\.deleted_attribute\b" nanobot/ tests/ --include="*.py"`

Also: clear mypy cache (`rm -rf .mypy_cache`) and re-run `make typecheck`.
All three greps must return zero matches (excluding comments and docs/).

## Refactoring Rules

- Refactor by seams, not by folders
- One PR, one change
- Tests first, then extract
- Preserve `__all__` exports without an ADR
- No speculative abstraction
- Run `make lint && make typecheck` after every edit

## Before Adding Any File — Placement Gate

**Every new `.py` file must pass this checklist before creation.**

1. **Name the owning package.** Which package's bounded context does this file serve?
   If it serves multiple packages — stop and restructure.

2. **Check the file count.** Will this addition push the package over 15 top-level files?
   If yes, plan a restructuring first.

3. **Infrastructure vs. implementation?** Tool infrastructure (base classes, registries,
   executors) lives at `tools/` level. Tool *implementations* live in `tools/builtin/`.
   Never mix them.

4. **Is it a catch-all?** Files named `utils.py`, `helpers.py`, `common.py`, or `misc.py`
   are prohibited.

5. **Will `__init__.py` need new exports?** If adding the export would exceed 12, the
   package is doing too much. Plan an extraction first.

6. **Check conventions.** Read 1-2 existing files in the target package. New code MUST
   follow existing conventions for connection/resource management, error handling, and
   async/sync boundaries.

## Before Growing a File — Size Gate

- **If the file is already > 400 LOC:** Assess whether it handles multiple concerns.
  If yes, extract the secondary concern *before* adding new code.
- **If your addition would push a file past 500 LOC:** Stop. Extract first, then add.
  The extraction is not optional and not a TODO — it happens now, in this session.
- **The only exception** is data-heavy files (schemas, constants, type definitions) that
  are large by nature. Mark these with `# size-exception: data definitions`.

## Package Growth Limits

**Hard limits — violations are bugs:**

| Metric | Threshold |
|--------|-----------|
| Top-level `.py` files in a package (excluding `__init__.py`) | <=15 |
| `__init__.py` exports (`__all__` entries) | <=12 |
| Single file LOC | <=500 |

**Advisory limits — trigger a design review:**

| Metric | Threshold |
|--------|-----------|
| Package total LOC | > 5,000 |
| Single file LOC | > 300 |
| Constructor parameters | > 7 |
