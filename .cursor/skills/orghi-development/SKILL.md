---
name: orghi-development
description: Default workflow for developing features and fixes in orghi. Use when adding features, implementing fixes, or starting development work. Covers path choice, TDD, direct core changes with documentation, handoff to **/code-simplifier agent** for code cleanup, and handoff to **/orghi-change-tracker agent** for change tracking. Handles feat/ and fix/ branches.
---

# Orghi Development

## Approach: Direct Changes + Documentation

**Make changes directly to core.** Document every change so merge conflicts can be resolved when syncing upstream.

**Goal:** Customize for your personal needs, PR when appropriate, minimize conflict resolution pain. When conflicts occur, tracking artifacts tell us the expected outcome. Worst case: accept upstream, rebuild from the tracking doc.

## Branch Types

- **feat/** - New features (e.g. `feat/adding-imessage-support`)
- **fix/** - Bug fixes (e.g. `fix/telegram-crash`)

## Mandatory First Step: Path Choice + Analysis

**Always ask and analyze before starting:**

1. **Analyze the request**: Is this generally useful to nanobot users (upstream-worthy)? Does it depend on orghi-specific code customizations? Could it be upstreamed later?
2. **Present the path options** (see Decision Matrix below) and recommend one based on the analysis.
3. **Do not proceed** until the user confirms.

**Default bias**: Prefer Path A (upstream) when the change is useful to others. Use Path B only when clearly personal. Use Path C when you want to dogfood on orghi-main first, then upstream.

## Decision Matrix

| Path | Branch from | Tests in | Merge to | PR? | When to use |
|------|-------------|----------|----------|-----|-------------|
| **A: Upstream PR** | main | `tests/` | N/A (push, open PR) | Yes | Generally useful; no orghi deps |
| **B: Orghi-only** | orghi-main | `tests/orghi/` | orghi-main | No | Personal; never upstreaming |
| **C: Orghi-first, upstream-later** | orghi-main | `tests/orghi/` | orghi-main first | Yes, after migration | Dogfood first; migrate to main + PR later |

## Surface Flows

**Path A:**
```
plan → feat/* or fix/* from main → tests → code → full test suite → handoff to **/code-simplifier agent** → handoff to **/orghi-change-tracker agent** → push → open PR
```

**Paths B, C:**
```
plan → feat/* or fix/* from orghi-main → tests → code → full test suite + orghi tests → handoff to **/code-simplifier agent** → handoff to **/orghi-change-tracker agent** → merge to orghi-main
```
(Later for Path C: migrate to main, push, handoff to **/orghi-change-tracker agent**, open PR - see Migration section.)

---

## Change Documentation

**Every change must be documented** for conflict resolution. The **/orghi-change-tracker agent** creates the tracking artifact.

**Tracking artifact:** `.orghi/orghi-change-tracking/<prefix>/<slug>.md` where branch is `<prefix>/<slug>` (e.g. `feat/adding-imessage-support` -> `feat/adding-imessage-support.md`; `fix/telegram-crash` -> `fix/telegram-crash.md`). Contains:
- Files touched, purpose per file
- What the change fixes/improves
- Conflict resolution guidance per file
- Worst case: accept upstream, rebuild steps (high-level, enough to re-implement)

**Before merge (B, C) or before open PR (A)**, the workflow **must** hand off to **/orghi-change-tracker agent** to create or update the artifact.

---

## Workflow Steps

### 1. Plan

Brief spec: what the change does, key behaviors, edge cases. Enough to write tests.

### 2. Create feat/<slug> or fix/<slug> Branch

Use a descriptive slug (e.g. `adding-imessage-support`, `telegram-crash`). Branch maps to document `.orghi/orghi-change-tracking/<prefix>/<slug>.md`.

**Path A (from main):**
```bash
git fetch origin
git checkout main
git pull origin main
git checkout -b feat/new-feature
# or: git checkout -b fix/telegram-crash
```

**Paths B, C (from orghi-main):**
```bash
git fetch origin
git checkout orghi-main
git pull origin orghi-main
git checkout -b feat/new-feature
# or: git checkout -b fix/telegram-crash
```

### 3. TDD: Write Tests First (RED)

**Iron law:** No production code without a failing test first.

- One minimal test per behavior.
- Test name describes behavior: `test_rejects_empty_email`, `test_retries_three_times`.
- Use real code; mocks only when unavoidable.
- Run: `uv run pytest path/to/test_file.py -v`
- **Verify the test fails** for the right reason (feature/fix missing, not typo).

**Test location:** Path A -> `tests/`. Paths B, C -> `tests/orghi/`.

**Python/pytest:** `@pytest.mark.asyncio` for async. `pytest.raises(ValueError, match="...")` for expected exceptions.

### 4. Write Minimal Code (GREEN)

- Smallest code to pass the test.
- No extra features. Keep tests green.

### 5. Run Full Test Suite

```bash
uv run pytest
```

**Paths B, C only:** also run orghi tests:
```bash
uv run pytest tests/orghi -v
```

All must pass.

### 6. Run Code-Simplifier

After tests pass, run **/code-simplifier agent** for cleanup (refactor, dedupe, align with patterns). Re-run full suite (and orghi tests if B/C) after.

### 7. Handoff to orghi-change-tracker (ALL paths, mandatory)

**Before push (A) or merge (B, C)**, invoke **/orghi-change-tracker agent** to create the tracking artifact. Ensures the commit and code pushed/merged has changes tracked.

**Handoff prompt:**
> Use the **/orghi-change-tracker agent** to track the changes for [prefix]/[slug]. The change [brief description]. Base branch was [main|orghi-main].

The tracker will:
1. Gather the diff (files touched)
2. Write `.orghi/orghi-change-tracking/<prefix>/<slug>.md` with purpose, conflict resolution, worst-case rebuild steps

**Do not push (A) or merge (B, C) until the tracking artifact is written.**

### 8. Push (Path A) or Merge (Paths B, C)

**Path A:** Push branch:
```bash
git push origin feat/new-feature
# or: git push origin fix/telegram-crash
```

**Paths B, C:** Merge to orghi-main:
```bash
git checkout orghi-main
git merge feat/new-feature
# or: git merge fix/telegram-crash
git push origin orghi-main
```

### 9. Open PR (Path A only)

**Path A:** Open PR after push. **Path B:** Done after merge. **Path C:** Done after merge; PR happens later during migration.

**PR title:** Short, imperative (e.g. `feat(channel): add send_only mode for Telegram` or `fix(telegram): resolve crash on reconnect`)

**PR body:**
```markdown
## Problem
What gap or pain does this address? 1-3 sentences.

## Solution
What does this change do? How does it work? Be concrete.

## Use Case
Who uses it? When? Example scenario.
```

Include test coverage notes. Link to issues if applicable.

---

## Conflict Resolution (Sync Upstream)

When merging main into orghi-main (sync-upstream), conflicts may occur. Use:

1. **File rules** in sync-upstream skill (README, __init__, etc.)
2. **Tracking artifacts** in `.orghi/orghi-change-tracking/feat/` and `.orghi/orghi-change-tracking/fix/` for change-specific guidance
3. **Worst case**: Accept all upstream. Rebuild using the "Worst Case: Accept Upstream, Rebuild" section in the tracking doc.

---

## Migration: Orghi-Main -> Upstream PR (Path C only)

When a Path C change on orghi-main becomes upstreamable:

1. **Create feat/* or fix/* from main** (main synced with upstream).
2. **Port the changes** - Copy from orghi-main into the branch. Strip orghi-specific bits. Use the tracking doc as reference (`.orghi/orghi-change-tracking/<prefix>/<slug>.md`).
3. **Move tests** from `tests/orghi/` to `tests/` if applicable.
4. **Run** `uv run pytest`, **/code-simplifier agent**, re-run tests.
5. **Handoff to orghi-change-tracker agent** for the new branch context (before push).
6. **Push branch**, open PR to upstream/main.
7. **After upstream merge**: Sync main, merge into orghi-main. Remove duplicate; orghi-main uses upstream.

---

## TDD Rules (Strict)

| Rule | Meaning |
|------|---------|
| Test first | Write failing test before implementation. Always. |
| Verify RED | Run test, confirm it fails for expected reason. |
| Verify GREEN | Run test, confirm it passes. |
| Minimal code | Only enough to pass. No YAGNI. |
| No test-after | Code first? Delete it. Start over with test. |

**Red flags:** Test passes immediately; "I'll add tests later"; changing tests to make code pass.

---

## Verification Checklist

- [ ] Analyze request and present path options (A, B, or C)
- [ ] Path choice confirmed (A, B, or C)
- [ ] Branch type chosen (feat/ or fix/)
- [ ] Tests in correct dir: `tests/` (A) or `tests/orghi/` (B, C)
- [ ] Each behavior has failing test first; seen to fail then pass
- [ ] `uv run pytest` passes
- [ ] `uv run pytest tests/orghi -v` passes (B, C)
- [ ] **/code-simplifier agent** run; tests still pass
- [ ] **/orghi-change-tracker agent** invoked before push/merge; tracking artifact written
- [ ] Path A: pushed branch, PR opened
- [ ] Paths B, C: merged into orghi-main
- [ ] PR (if applicable) has title, problem, solution, use case

---

## References

- Branch strategy: `.cursor/rules/orghi-project-context.mdc`
- Sync upstream: `.cursor/skills/sync-upstream/SKILL.md`
- Change tracking: `.orghi/orghi-change-tracking/` (created by **/orghi-change-tracker agent**)
- TDD inspiration: test-driven-development skill (Red-Green-Refactor)
