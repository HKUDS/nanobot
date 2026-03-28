# CLAUDE.md Comprehensive Audit — Accuracy, Hooks, and Documentation Strategy

> Date: 2026-03-28
> Scope: CLAUDE.md (607 lines), 11 ADRs, docs/architecture.md, documentation drift analysis
> Input: Post-refactor introspection (7 failure modes), redesign spec (15 patterns),
> line-by-line CLAUDE.md rule extraction (117 rules), ADR accuracy audit, architecture.md audit

---

## Executive Summary

CLAUDE.md contains **117 prescriptive rules** across 12 sections. Of these:
- **~15 are already hard-enforced** by CI scripts (check_imports, check_structure, ruff, mypy)
- **~5 are covered** by the SessionStart hook checklist
- **~60+ rely entirely on soft enforcement** (Claude reading and following them)
- **~25 cannot be automated** (require architectural judgment)

The audit found **6 stale references** in CLAUDE.md, **2 ADRs with drift** (ADR-002 not
marked superseded, ADR-008 prompt names outdated), and **7 discrepancies** in
docs/architecture.md (including references to the deleted Coordinator class).

The documentation drift problem is systemic — every major refactoring leaves documentation
stale because doc updates are treated as an afterthought, not as part of the change.

**27 hook opportunities** were identified that can close the gap between CI enforcement
(post-hoc) and real-time prevention (during editing). The highest-impact hooks are:
commit message validation, branch protection, file placement reminders, and file size gates.

---

## Part 1: CLAUDE.md Accuracy Issues

### Stale References (6)

| Line | Issue | Current State |
|------|-------|---------------|
| 65 | References `_ChatProvider` in context.py | Does not exist — no Protocol by that name in the file |
| 83 | coordination/ described with "routing" | Routing removed in Phase 1. Should be "delegation, missions, scratchpad" |
| 432 | Orphaned line "value object), it's a violation." | Corrupted text — duplicate fragment from an earlier edit |
| 458-460 | References `tests/contract/test_routing_invariant.py` | Deleted in Phase 1. The invariant rule is valid but the test is gone |
| 472 | References `.github/prompts/` | Directory does not exist |
| 40-45 | Version examples use "0.2.0 → 0.3.0" | Current version is 1.0.1 |

### Outdated Descriptions (3)

| Line | Issue | Fix |
|------|-------|-----|
| 83 | "Multi-agent routing, delegation, missions, scratchpad" | Remove "routing" |
| 100-104 | "agent/ monolith (25k LOC, 68 files, 23 exports)" | Currently 13 files. Add "(historical)" |
| 169-170 | "loop.py grew to 1,025 LOC" | Now 402 LOC. Mark as historical |

---

## Part 2: ADR Drift Analysis

### ADR-002: Agent Loop Ownership — **SUPERSEDED, NOT MARKED**

The most significant drift. ADR-002 describes the PAOR loop architecture with
TurnOrchestrator, ActPhase, ReflectPhase. ADR-011 supersedes it with TurnRunner.
But ADR-002 has no status update indicating supersession. A future session reading
ADR-002 gets outdated architecture guidance.

**Fix:** Add `Status: Superseded by ADR-011` at the top of ADR-002.

### ADR-008: Prompt Management — **Minor Naming Drift**

Lists prompts as `system.md`, `plan.md`, `reflect.md`, `verify.md`. Actual files are
`identity.md`, `reasoning.md`, `tool_guide.md`, `self_check.md`. The implementation
evolved during the redesign.

**Fix:** Update prompt file names in ADR-008, or add a note: "Prompt names evolved
during the ADR-011 cognitive redesign."

### ADR-011: Agent Cognitive Redesign — **Minor LOC Inaccuracy**

Says "TurnRunner, ~573 LOC". Actual is 601 LOC. Trivial but documented.

### All Other ADRs (001, 003-007, 009-010): **Accurate** ✓

---

## Part 3: docs/architecture.md Discrepancies (7 found)

| Location | Issue | Fix |
|----------|-------|-----|
| Line ~40 | Lists `Coordinator` as key class in coordination/ | Coordinator was deleted — remove |
| Line ~145 | Data flow: `Coordinator.classify() determines target role` | Delete — this flow no longer exists |
| Line ~146 | `Child AgentLoop.run_tool_loop()` | Method doesn't exist — update to actual delegation flow |
| Line ~192 | References `memory/migration.py` | File deleted — remove reference |
| Line ~132 | `ContextBuilder.build() assembles prompt` | Method is `build_system_prompt()` and `build_messages()` — fix name |
| Line ~155 | `MemoryExtractor.extract(messages)` | Method is `extract_structured_memory()` — fix name |
| Lines 197-224 | Memory subsystem file listing incomplete | Missing 6 files in write/ and read/ subdirectories |

---

## Part 4: The Documentation Drift Problem

### Why Docs Always Drift

Every major refactoring in this project leaves documentation stale:
- Phase 1 deleted coordinator.py but docs/architecture.md still references Coordinator
- Phase 3 replaced TurnOrchestrator but ADR-002 still describes it
- Phase 4 changed prompt names but ADR-008 still lists old names
- CLAUDE.md references deleted test files and non-existent directories

The root cause is structural: **documentation updates are treated as a Phase 6 (cleanup)
task, but Phase 6 only catches what the cleanup agent looks for.** Stale references
survive because the cleanup grep patterns are incomplete.

### Proposed Solution: Documentation as a Gated Artifact

**Principle:** If code changes X, and document Y describes X, then Y must be updated
in the same PR — not deferred to cleanup.

**Implementation options:**

#### Option A: Hook-Based Doc Staleness Detection

A PostToolUse hook on Edit/Write that checks if the changed file is referenced in docs:

```bash
# When nanobot/agent/turn_runner.py is edited:
# Check if docs reference TurnRunner or turn_runner
grep -rl "turn_runner\|TurnRunner" docs/ CLAUDE.md | head -5
# If matches found, inject: "Files that reference this code: [list].
# Verify they're still accurate."
```

**Effort:** Medium. Useful as an advisory — can't validate content accuracy, but can
flag which docs MIGHT need updating.

#### Option B: Documentation Manifest (Like Prompt Manifest)

A `docs_manifest.json` that maps code files to their documentation references:

```json
{
  "nanobot/agent/turn_runner.py": [
    "CLAUDE.md:76-80",
    "docs/architecture.md:40",
    "docs/adr/ADR-011-agent-cognitive-redesign.md"
  ],
  "nanobot/coordination/delegation.py": [
    "docs/architecture.md:145-148",
    "CLAUDE.md:82-83"
  ]
}
```

A CI script (`check_doc_references.py`) verifies that referenced files exist and
that key class/function names still match.

**Effort:** Large initial setup, but catches drift automatically in CI.

#### Option C: ADR Status Tracking Script

A lightweight script that checks ADR files for consistency:
- All ADRs have a Status field (Accepted, Superseded, Deprecated)
- If Status: Superseded, the superseding ADR exists
- If an ADR references a file, that file exists

**Effort:** Small. Add to `make check`.

#### Recommended: Option A + C

Option A (advisory hook) is low-effort and catches the most common case: "you changed
code that docs reference." Option C (ADR status tracking) prevents the ADR-002 problem
(superseded but unmarked). Option B is ideal but high-effort for the current project
stage.

---

## Part 5: Hook Opportunity Summary (27 High-Value Hooks)

### Tier 1: Hard Blocks (exit 2) — Prevent Violations

| # | Hook | Event + Matcher | Rules | Effort |
|---|------|-----------------|-------|--------|
| 1 | Conventional commit format | PreToolUse `Bash(git commit*)` | 4 | small |
| 2 | No implementation commits to main | PreToolUse `Bash(git commit*)` | 116 | small |
| 3 | Banned filenames (utils, helpers, common, misc) | PreToolUse `Write(nanobot/**/{utils,helpers,common,misc}.py)` | 22, 59, 93 | trivial |
| 4 | No MemoryError class | PostToolUse `Edit\|Write(*.py)` | 111 | trivial |
| 5 | Version field protection | PreToolUse `Edit(pyproject.toml)` | 5 | small |
| 6 | File size >500 LOC block | PostToolUse `Edit\|Write(*.py)` | 15, 26, 99 | small |
| 7 | Package file count >=15 block | PreToolUse `Write(nanobot/*/*.py)` | 13, 20, 94 | small |
| 8 | Init export count >12 block | PostToolUse `Edit\|Write(*__init__.py)` | 14, 23, 95 | small |
| 9 | future annotations on new files | PostToolUse `Write(*.py)` | 7 | trivial |
| 10 | Hardcoded secrets detection | PostToolUse `Edit\|Write(*.py)` | 41 | small |
| 11 | Deferred-move TODOs blocked | PostToolUse `Edit\|Write(*.py)` | 57 | small |

### Tier 2: Advisories (systemMessage) — Remind Without Blocking

| # | Hook | Event + Matcher | Rules | Effort |
|---|------|-----------------|-------|--------|
| 12 | Placement gate reminder | PreToolUse `Write(nanobot/**/*.py)` | 19, 24, 62 | trivial |
| 13 | File size >400 LOC warning | PreToolUse `Edit(nanobot/**/*.py)` | 25 | small |
| 14 | Tool in wrong dir warning | PreToolUse `Write(nanobot/tools/*.py)` | 21, 39, 50 | trivial |
| 15 | Memory flat file warning | PreToolUse `Write(nanobot/memory/*.py)` | 51, 91 | trivial |
| 16 | Module deletion reminder | PostToolUse `Bash(rm*nanobot*.py)` | 80, 81 | small |
| 17 | Pre-push reminder | PreToolUse `Bash(git push*)` | 115 | trivial |
| 18 | Test coverage check | PreToolUse `Bash(git commit*)` | 76 | small |
| 19 | Loop logic warning | PostToolUse `Edit(turn_runner.py)` | 107 | trivial |
| 20 | Doc review reminder on commit | PreToolUse `Bash(git commit*)` | 3, 77 | trivial |
| 21 | Tool registration reminder | PostToolUse `Write(nanobot/tools/builtin/*.py)` | 114 | trivial |
| 22 | Crash-barrier check | PostToolUse `Edit\|Write(*.py)` | 31, 97 | small |
| 23 | raise Exception check | PostToolUse `Edit\|Write(*.py)` | 30 | small |
| 24 | Blocking I/O detection | PostToolUse `Edit\|Write(*.py)` | 12 | small |
| 25 | Union syntax check | PostToolUse `Edit\|Write(*.py)` | 6 | small |
| 26 | Subsystem construction outside factory | PostToolUse `Edit(nanobot/agent/loop.py)` | 52, 53 | medium |
| 27 | Doc staleness advisory | PostToolUse `Edit\|Write(nanobot/**/*.py)` | docs | medium |

### Not Hookable (~25 rules)

Rules requiring architectural judgment: Protocol design, domain logic assessment,
refactoring philosophy, data contract design, spec deviation tracking, single
pipeline convergence analysis. These remain CLAUDE.md-only.

---

## Part 6: CLAUDE.md Restructuring Proposal

### Current: 607 lines, everything in one file

### Problem: Every session loads 607 lines into context

At ~4 chars/token, 607 lines ≈ 2,400 tokens of context consumed before Claude reads
a single code file. On a 16K model, that's 15% of context for instructions.

### Proposed: ~250 lines in CLAUDE.md + path-scoped rules files

**Main CLAUDE.md (~250 lines):** Essential commands, critical constraints, architecture
summary, pointers to rules files.

**`.claude/rules/` (path-scoped, loaded on demand):**

| File | Content | Path Scope | LOC |
|------|---------|------------|-----|
| `architecture-constraints.md` | Boundaries table, dependency inversion, composition root, single pipeline | `nanobot/**/*.py` | ~80 |
| `placement-gate.md` | Before adding/growing files checklist | `nanobot/**/*.py` | ~40 |
| `prohibited-patterns.md` | Full prohibited patterns list | `nanobot/**/*.py` | ~50 |
| `change-protocol.md` | Before/after change procedures, deletion grep | (always loaded) | ~60 |
| `git-workflow.md` | Worktree protocol, branch strategy | (always loaded) | ~35 |
| `adding-components.md` | New tool/skill procedures | `nanobot/tools/**`, `nanobot/skills/**` | ~30 |
| `growth-limits.md` | Package limits, how to check, advisory thresholds | `nanobot/**/*.py` | ~30 |

**Benefits:**
- CLAUDE.md is 250 lines (down from 607) — loads on every session
- Architecture rules load only when editing Python (not on doc-only sessions)
- Adding-components rules load only when editing tools/skills
- Total content unchanged — just organized for context efficiency

### What Changes in CLAUDE.md

**Sections that STAY (trimmed to essentials):**
- Who Develops This (5 lines)
- After Every Edit / Before Committing (10 lines)
- Commit Message Convention (15 lines — also enforced by hook)
- Python Conventions (8 lines)
- Architecture Layers (15 lines — SUMMARY only, pointer to rules file)
- Coding Standards (8 lines — note which are script-enforced)
- Testing (15 lines — include test data requirements)
- Memory System Architecture (10 lines)
- Security Rules (5 lines)
- Architecture References (8 lines — updated for ADR-011)
- Known Gotchas (3 lines)

**Sections that MOVE to rules files:**
- Package Growth Limits (34 lines → growth-limits.md)
- Placement Gate (32 lines → placement-gate.md)
- Size Gate (12 lines → placement-gate.md)
- Non-Negotiable Constraints (105 lines → architecture-constraints.md)
- Change Protocol (70 lines → change-protocol.md)
- Prohibited Patterns (55 lines → prohibited-patterns.md)
- Git Worktree Protocol (35 lines → git-workflow.md)
- Adding Tool/Skill (30 lines → adding-components.md)
- Dev Commands (25 lines → move to `make help` or dev-commands.md)

**Sections that are REDUNDANT (remove or simplify):**
- Growth limits "How to check" bash commands — these are in the scripts
- Prohibited patterns that duplicate script enforcement — keep one-line reference
- Import direction table — enforced by check_imports.py, link to rules file

---

## Part 7: Implementation Plan

### Phase 1: Fix Accuracy Issues (immediate)

1. Fix 6 stale references in CLAUDE.md
2. Fix 3 outdated descriptions
3. Mark ADR-002 as superseded by ADR-011
4. Fix 7 discrepancies in docs/architecture.md
5. Update ADR-008 prompt file names

### Phase 2: Create Hooks (small effort, high value)

Create hook scripts and update `.claude/settings.json`:
- Tier 1 hooks #1-5 (commits, main branch, filenames, MemoryError, version)
- Tier 2 hooks #12, 17, 20 (placement gate, pre-push, doc review reminders)

### Phase 3: Create Rules Files + Slim CLAUDE.md

1. Create `.claude/rules/` directory with 7 rules files
2. Rewrite CLAUDE.md to ~250 lines with pointers
3. Verify rules files load correctly with path scoping

### Phase 4: Documentation Drift Prevention

1. Create ADR status checking script (Option C)
2. Add doc staleness advisory hook (Option A)
3. Add to CLAUDE.md: "Code changes that affect documented behavior must update
   docs in the same PR"
