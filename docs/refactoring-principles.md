# Refactoring Principles

> Rules for safe, incremental refactoring of the Nanobot codebase.

## Core Principles

### 1. Refactor by seams, not by folders

Extract internal interfaces and sub-services first. Moving files into new directories is
the last step, not the first.

**Good:** Extract `ToolExecutor` class from `loop.py` into `tool_executor.py` in the same
package.

**Bad:** Rename `agent/` to `agent_core/` and restructure everything at once.

### 2. One PR, one change

Each refactor PR should do exactly one thing:
- Extract a module
- Add a contract test
- Externalize prompts
- Update an ADR

Never combine unrelated refactors in the same PR. If a refactor reveals a second needed
change, open a separate issue.

### 3. Tests first

Before extracting any code:
1. Ensure existing tests cover the current behavior.
2. If coverage is insufficient, add tests *before* the refactor (in a separate PR).
3. After extraction, all existing tests must still pass without modification to test
   logic (only import paths may change).

### 4. Preserve public API

Refactors must not change the public API of a module unless explicitly documented in an
ADR. Public API = what is listed in `__all__` of the module's `__init__.py`.

### 5. No speculative abstraction

Only abstract when there are at least two concrete implementations or when an ADR
justifies the abstraction. Do not create helpers, utilities, or wrappers for one-time
operations.

### 6. Verify after every change

```bash
make lint && make typecheck    # After every edit
make check                     # Before every commit
```

If `make check` fails, fix it before proceeding.

## Refactoring Workflow

```
1. Open issue describing the refactor goal
2. Write or update the relevant ADR (if architectural)
3. Create a feature branch
4. Add/verify tests for current behavior
5. Make the refactor in a single focused PR
6. Run `make check`
7. Open PR with description referencing the issue and ADR
8. Get review (Copilot + human)
9. Merge only after CI passes
```

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Dangerous |
|---|---|
| "While I'm here" changes | Mixes unrelated changes, makes review and rollback harder |
| Renaming packages for aesthetics | Breaks imports everywhere, high risk for low value |
| Adding abstraction layers "for the future" | Creates dead code and indirection with no benefit |
| Rewriting before measuring | Changes behavior without knowing what behavior was correct |
| Bypassing CI with `--no-verify` | Defeats the purpose of guardrails |
| Large PRs (>500 lines changed) | Hard to review, high risk of hidden regressions |

## Extraction Checklist

When extracting a sub-service from a larger module:

- [ ] Current behavior is covered by tests
- [ ] New module has a clear, minimal public API
- [ ] New module does not introduce circular imports
- [ ] `__all__` updated in relevant `__init__.py` (only if the new module is public)
- [ ] Existing tests pass without logic changes
- [ ] `make check` passes
- [ ] ADR written or updated (if the extraction changes module boundaries)
