# CLAUDE.md Audit, Accuracy Fixes, and Hook Enforcement — Design Spec

> Date: 2026-03-28
> Status: **Proposed**
> Context: CLAUDE.md is 607 lines. Post-refactor audit found that soft enforcement
> (relying on Claude reading and following CLAUDE.md) failed — every critical finding
> would have been caught by hooks. This spec proposes accuracy fixes, hook-based
> enforcement of mechanical rules, and structural organization improvements.

---

## Part 1: Accuracy Audit — What's Wrong in CLAUDE.md

### Stale References (6 found)

| Line | Issue | Fix |
|------|-------|-----|
| 65 | References `_ChatProvider` in `context.py` — does not exist | Remove reference or update to actual Protocol name |
| 83 | coordination/ described as "Multi-agent routing, delegation, missions, scratchpad" — routing was removed in Phase 1 | Change to "Multi-agent delegation, missions, scratchpad" |
| 432 | Orphaned fragment "value object), it's a violation." — duplicate/corrupted line | Delete line |
| 458-460 | References `tests/contract/test_routing_invariant.py` — deleted in Phase 1 | Remove reference. The single-pipeline invariant is still valid but the test file is gone. |
| 472 | References `.github/prompts/` — directory does not exist | Remove reference |
| 40-45 | Commit convention examples use "0.2.0 → 0.3.0" — current version is 1.0.1 | Update examples to use 1.0.x range |

### Outdated Descriptions (3 found)

| Line | Issue | Fix |
|------|-------|-----|
| 83 | coordination/ still mentions "routing" | Remove "routing" |
| 100-104 | Historical context references "agent/ monolith (25k LOC, 68 files)" — true historically but misleading as current state | Add "(historical)" qualifier |
| 169-170 | "loop.py grew to 1,025 LOC and delegation.py to 1,002 LOC" — loop.py is now 402, delegation is ~508 | Update numbers or mark as historical |

### Missing Information (4 found)

| Area | What's Missing |
|------|---------------|
| Architecture Layers | No mention of TurnRunner, GuardrailChain, or procedural memory (StrategyStore) |
| Testing section | No mention of contract tests (`tests/contract/`) or the 16 spec contract tests |
| Dev Commands | `make phase-todo-check` is listed but description could be clearer |
| Prohibited Patterns | Missing: "Domain logic in the loop" — the most important new constraint |

---

## Part 2: What Should Be Hooks vs CLAUDE.md

### Decision Framework

| Rule Type | Enforcement | Mechanism |
|-----------|-------------|-----------|
| **Mechanical, no judgment** | Hook (hard) | PreToolUse/PostToolUse scripts |
| **Requires context about the task** | CLAUDE.md (soft) | Read and follow |
| **Requires codebase knowledge** | Script (hard) | check_imports, check_structure |
| **Requires architectural judgment** | CLAUDE.md + memory (soft) | Design decisions |

### Rules to Migrate to Hooks

| Current CLAUDE.md Rule | Hook Type | Why Migrate |
|------------------------|-----------|-------------|
| "Conventional Commits format" | PreToolUse on `Bash(git commit*)` | Mechanical validation — no judgment needed |
| "Never manually edit __version__" | PreToolUse on `Edit\|Write` | Pure prevention — detect version string edits |
| "Don't commit to main" | PreToolUse on `Bash(git commit*)` | Check current branch — block if main |
| "run make pre-push before pushing" | PreToolUse on `Bash(git push*)` | Deterministic gate — run validation suite |

### Rules to KEEP in CLAUDE.md Only

| Rule | Why NOT a Hook |
|------|---------------|
| "After every edit: make lint && make typecheck" | Too slow as PostToolUse — fires on every Write/Edit (~5-10s). Better as discipline. |
| Architecture layers description | Context information, not enforceable |
| Placement Gate checklist | Requires judgment about package ownership |
| Size Gate | Already enforced by check_structure.py in pre-commit |
| Package boundaries table | Already enforced by check_imports.py in pre-commit |
| Prohibited patterns | Most already enforced by scripts; remainder needs judgment |
| Worktree protocol | Positive workflow guidance, not blockable |
| Change protocol | Requires architectural reasoning |

### Rules That Are REDUNDANT with Existing Scripts

These are in CLAUDE.md AND enforced by pre-commit scripts. Keep a brief mention in
CLAUDE.md for context, but the enforcement is already hard:

| CLAUDE.md Rule | Script | Can Simplify? |
|----------------|--------|---------------|
| "≤ 15 files per package" | check_structure.py | Yes — just reference the script |
| "≤ 12 __init__.py exports" | check_structure.py | Yes |
| "≤ 500 LOC per file" | check_structure.py | Yes |
| "No catch-all modules" | check_structure.py | Yes |
| "crash-barrier comments on except Exception" | check_structure.py | Yes |
| "from __future__ import annotations" | check_structure.py | Yes |
| "Import direction rules" | check_imports.py | Yes |
| "TYPE_CHECKING imports reference existing modules" | check_imports.py (new) | Yes |
| "No TODOs for completed phases" | check_phase_todos.py (new) | Yes |
| "Prompt manifest consistency" | check_prompt_manifest.py | Yes |

---

## Part 3: Proposed Hooks

### Hook 1: Conventional Commits Validator

**Trigger:** PreToolUse on `Bash(git commit*)`
**What it does:** Validates commit message matches `type(scope): description` pattern
**Why:** The introspection found we commit frequently. Invalid commit messages break semantic-release. Currently relies on Claude remembering the format from CLAUDE.md.

```json
{
  "matcher": "Bash",
  "if": "Bash(git commit*)",
  "hooks": [
    {
      "type": "command",
      "command": ".claude/hooks/validate-commit.sh",
      "timeout": 10
    }
  ]
}
```

Script `.claude/hooks/validate-commit.sh`:
```bash
#!/bin/bash
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Skip if not a -m commit (interactive commits handled by git hooks)
MSG=$(echo "$CMD" | sed -n 's/.*-m[[:space:]]*["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' | head -1)
[ -z "$MSG" ] && exit 0

# Allow multi-line: check only first line
FIRST=$(echo "$MSG" | head -1)

# Conventional Commits: type(scope): description
if echo "$FIRST" | grep -qE '^(feat|fix|perf|refactor|docs|test|chore|ci)(\([a-zA-Z0-9_-]+\))?!?:\s'; then
  exit 0
fi

# Also allow merge commits and release commits
if echo "$FIRST" | grep -qE '^(Merge|chore\(release\))'; then
  exit 0
fi

echo '{"systemMessage": "Commit message does not follow Conventional Commits format. Required: type(scope): description. Types: feat, fix, perf, refactor, docs, test, chore, ci"}'
exit 0
```

Note: Uses `systemMessage` instead of `exit 2` — warns but doesn't hard-block. Claude
can self-correct.

### Hook 2: No Direct Commits to Main

**Trigger:** PreToolUse on `Bash(git commit*)`
**What it does:** Blocks commits when current branch is `main`
**Why:** The introspection and session showed we committed docs directly to main repeatedly. Implementation should always go through feature branches.

```json
{
  "matcher": "Bash",
  "if": "Bash(git commit*)",
  "hooks": [
    {
      "type": "command",
      "command": ".claude/hooks/no-main-commits.sh",
      "timeout": 5
    }
  ]
}
```

Script `.claude/hooks/no-main-commits.sh`:
```bash
#!/bin/bash
BRANCH=$(git branch --show-current 2>/dev/null)
[ "$BRANCH" != "main" ] && exit 0

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
MSG=$(echo "$CMD" | sed -n 's/.*-m[[:space:]]*["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' | head -1)

# Allow docs-only commits to main (specs, plans, reports, CLAUDE.md)
if echo "$MSG" | grep -qE '^docs(\([a-zA-Z-]+\))?:'; then
  exit 0
fi

# Allow chore commits (release, cleanup)
if echo "$MSG" | grep -qE '^chore(\([a-zA-Z-]+\))?:'; then
  exit 0
fi

# Block feat/fix/refactor/test commits to main
echo '{"systemMessage": "WARNING: You are committing implementation code directly to main. Use a feature branch + worktree per CLAUDE.md Git Worktree Protocol. Only docs/chore commits are allowed on main."}'
exit 0
```

### Hook 3: Version Protection

**Trigger:** PreToolUse on `Edit`
**What it does:** Warns when editing version strings in pyproject.toml or __init__.py
**Why:** semantic-release manages versions. Manual edits cause version conflicts.

```json
{
  "matcher": "Edit",
  "hooks": [
    {
      "type": "command",
      "command": ".claude/hooks/protect-version.sh",
      "timeout": 5
    }
  ]
}
```

Script `.claude/hooks/protect-version.sh`:
```bash
#!/bin/bash
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
NEW=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')

# Only check pyproject.toml and __init__.py
case "$FILE" in
  *pyproject.toml|*__init__.py)
    if echo "$NEW" | grep -qE '__version__|^version\s*='; then
      echo '{"systemMessage": "WARNING: Editing version string. python-semantic-release manages versions automatically. Only edit if fixing a release config issue."}'
    fi
    ;;
esac
exit 0
```

### Hook 4: Pre-Push Validation

**Trigger:** PreToolUse on `Bash(git push*)`
**What it does:** Reminds to run `make pre-push` before pushing
**Why:** The introspection found that `make check` != CI. `make pre-push` includes
coverage and merge-readiness checks that `make check` doesn't.

```json
{
  "matcher": "Bash",
  "if": "Bash(git push*)",
  "hooks": [
    {
      "type": "command",
      "command": ".claude/hooks/pre-push-reminder.sh",
      "timeout": 5
    }
  ]
}
```

Script `.claude/hooks/pre-push-reminder.sh`:
```bash
#!/bin/bash
# Don't block — just remind. Running make pre-push here would be too slow.
echo '{"systemMessage": "REMINDER: Did you run make pre-push? It catches issues that make check misses (coverage gate, mypy with clean cache, merge-readiness)."}'
exit 0
```

Note: Advisory only (systemMessage, not exit 2). Running `make pre-push` inside the
hook would add 2-3 minutes to every push. The reminder is sufficient — Claude will
see it and run the command if needed.

---

## Part 4: CLAUDE.md Restructuring

### Current: 607 lines in one file

### Proposed: ~250 lines in CLAUDE.md + rules files

The principle: **CLAUDE.md is the executive summary. Rules files are the reference.**

CLAUDE.md should contain:
1. What to run and when (commands)
2. Critical constraints that EVERY session must know
3. Pointers to detailed docs

Rules files (`.claude/rules/`) contain:
1. Detailed architectural descriptions
2. Package-specific conventions
3. Checklists and procedures

### What Moves Out

| Section | Current LOC | Destination | Reason |
|---------|------------|-------------|--------|
| Package Growth Limits + How to Check | 34 | `.claude/rules/growth-limits.md` | Reference material, rarely needed mid-session |
| Before Adding Any File (Placement Gate) | 32 | `.claude/rules/placement-gate.md` | Checklist, needed only when creating files. Can be path-scoped to `nanobot/` |
| Before Growing a File (Size Gate) | 12 | `.claude/rules/placement-gate.md` | Same context as placement gate |
| Non-Negotiable Architectural Constraints | 105 | `.claude/rules/architecture-constraints.md` | Longest section. Most rules enforced by scripts. Keep a 3-line summary in CLAUDE.md |
| Change Protocol (Before/After) | 70 | `.claude/rules/change-protocol.md` | Detailed procedure, needed only during implementation |
| Prohibited Patterns | 55 | `.claude/rules/prohibited-patterns.md` | Reference list. Most enforced by scripts. |
| Git Worktree Protocol | 35 | `.claude/rules/git-workflow.md` | Procedure, needed only during git operations |
| Adding a New Tool / Skill | 30 | `.claude/rules/adding-components.md` | Procedure, needed only when adding tools/skills |
| Memory System Architecture | 10 | Keep in CLAUDE.md | Short, important context |
| Dev Commands | 25 | `.claude/rules/dev-commands.md` or just `make help` | Reference, already in Makefile |

### What Stays in CLAUDE.md

| Section | LOC | Why Keep |
|---------|-----|----------|
| Who Develops This | 5 | Identity — every session needs this |
| Project Overview | 2 | Identity |
| After Every Edit / Before Committing | 10 | Critical workflow — must be top of mind |
| Commit Message Convention | 15 | Frequently needed (will be enforced by hook too) |
| Python Conventions | 8 | Fundamental coding rules |
| Architecture Layers (SUMMARY) | 15 | Mental model — but trim to essentials |
| Coding Standards | 8 | Fundamental coding rules |
| Testing (SUMMARY) | 15 | Key commands + test data requirements |
| Memory System Architecture | 10 | Domain knowledge |
| Security Rules | 5 | Critical constraints |
| Architecture References | 8 | Pointers to detailed docs |
| Known Gotchas | 3 | Trap avoidance |

**Estimated CLAUDE.md after restructuring: ~200-250 lines**

### Path-Scoped Rules

```
.claude/rules/
├── architecture-constraints.md    # paths: nanobot/**/*.py
├── placement-gate.md              # paths: nanobot/**/*.py
├── prohibited-patterns.md         # paths: nanobot/**/*.py
├── change-protocol.md             # (no path restriction — always loaded)
├── git-workflow.md                 # (no path restriction)
├── adding-components.md           # paths: nanobot/tools/**/*.py, nanobot/skills/**
├── growth-limits.md               # paths: nanobot/**/*.py
└── dev-commands.md                # (no path restriction)
```

Path-scoped rules load only when Claude opens matching files. This means the
architecture constraints (105 lines) only load when Claude is actually editing
Python files — not when writing docs or reviewing plans.

---

## Part 5: Integration with Introspection Findings

The post-refactor introspection (`2026-03-28-post-refactor-introspection.md`)
identified 7 failure modes. Here's how the proposed hooks and restructuring address
them:

| Failure Mode | Current Enforcement | Proposed Addition |
|-------------|--------------------|--------------------|
| FM1: Plans bake in anti-patterns | CLAUDE.md rule (soft) + SessionStart checklist (medium) | Rule in `.claude/rules/change-protocol.md`: "Read existing code before designing" |
| FM2: Synthetic test data | CLAUDE.md rule (soft) | Rule in `.claude/rules/change-protocol.md`: "Test data requirements" |
| FM3: Cross-phase contracts | Contract tests (hard) | Already enforced by `test_data_contracts.py` |
| FM4: Incomplete deletion | check_imports.py TYPE_CHECKING check (hard) + CLAUDE.md grep procedure (soft) | Rule in `.claude/rules/change-protocol.md` |
| FM5: Lost TODOs | check_phase_todos.py (hard) | Already enforced |
| FM6: Spec drift | CLAUDE.md rule (soft) | Rule in `.claude/rules/change-protocol.md` |
| FM7: Skipped review | SessionStart checklist (medium) | Hook reminder (medium) — can't force, but visible |

### Alignment with Redesign Spec's 15 Patterns

The redesign spec (`2026-03-27-agent-cognitive-redesign.md`) defines 15 structural
stability patterns. Here's how enforcement maps:

| Pattern | Hard (script) | Medium (hook) | Soft (rules file) |
|---------|---------------|---------------|-------------------|
| 1. Loop Is Dumb | check_structure.py (partial) | — | architecture-constraints.md |
| 2. Guardrails Are Plugins | — | — | architecture-constraints.md |
| 3. Context Composable | — | — | architecture-constraints.md (NOTE: not yet implemented) |
| 4. Memory Three Tiers | — | — | CLAUDE.md (memory section) |
| 5. Feedback Loops | — | — | architecture-constraints.md |
| 6. Stable/Volatile | — | — | architecture-constraints.md |
| 7. One Reason to Change | — | — | prohibited-patterns.md |
| 8. Protocols at Boundaries | check_imports.py (partial) | — | architecture-constraints.md |
| 9. Three Extension Points | — | — | architecture-constraints.md |
| 10. Growth Limits | check_structure.py (hard) | — | growth-limits.md |
| 11. Observable | — | — | architecture-constraints.md |
| 12. No Implicit Coupling | — | — | prohibited-patterns.md |
| 13. Prompts Are Code | check_prompt_manifest.py (hard) | — | — |
| 14. Design for Deletion | — | — | architecture-constraints.md |
| 15. Contract Tests | pytest (hard) | — | change-protocol.md |

---

## Part 6: Implementation Plan

### Task 1: Fix CLAUDE.md accuracy issues

Fix the 6 stale references and 3 outdated descriptions identified in Part 1.

### Task 2: Create hook scripts

Create 4 hook scripts in `.claude/hooks/`:
- `validate-commit.sh` — Conventional Commits format
- `no-main-commits.sh` — Block implementation commits to main
- `protect-version.sh` — Warn on version string edits
- `pre-push-reminder.sh` — Remind to run make pre-push

### Task 3: Update .claude/settings.json

Add PreToolUse hooks for git commit, git push, and Edit operations.

### Task 4: Create rules files

Extract detailed sections from CLAUDE.md into `.claude/rules/`:
- `architecture-constraints.md`
- `placement-gate.md`
- `prohibited-patterns.md`
- `change-protocol.md`
- `git-workflow.md`
- `adding-components.md`
- `growth-limits.md`

### Task 5: Slim down CLAUDE.md

Rewrite CLAUDE.md to ~250 lines with pointers to rules files.

### Task 6: Verify

- All hooks fire correctly (test each trigger)
- Rules files load at appropriate times
- `make check` still passes
- Pre-commit hooks still work
