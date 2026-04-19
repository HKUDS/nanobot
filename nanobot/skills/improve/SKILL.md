---
name: improve
description: "Capture learnings, errors, and corrections for continuous improvement. Use when: (1) A command or operation fails unexpectedly, (2) User corrects your approach, (3) You discover a knowledge gap or better pattern, (4) User requests a missing capability. Activation phrases: log this, remember this, don't forget, I wish you could, why didn't you, you should have known."
always: true
---

# Self-Improvement

Log learnings, errors, and feature requests to `.learnings/` for continuous improvement.

## First-Use Initialization

Before logging anything, ensure the `.learnings/` directory and files exist in the workspace root:

```bash
mkdir -p .learnings
[ -f .learnings/LEARNINGS.md ] || printf "# Learnings\n\nCorrections, insights, and knowledge gaps captured during development.\n\n**Categories**: correction | insight | knowledge_gap | best_practice\n\n---\n" > .learnings/LEARNINGS.md
[ -f .learnings/ERRORS.md ] || printf "# Errors\n\nCommand failures and integration errors.\n\n---\n" > .learnings/ERRORS.md
[ -f .learnings/FEATURE_REQUESTS.md ] || printf "# Feature Requests\n\nCapabilities requested by the user.\n\n---\n" > .learnings/FEATURE_REQUESTS.md
```

This is a no-op if `.learnings/` is already initialized.

**Security**: Never log secrets, tokens, private keys, environment variables, or full source/config files. Prefer short summaries or redacted excerpts over raw command output.

## Quick Reference

| Situation | Action |
|-----------|--------|
| Command/operation fails | Log to `.learnings/ERRORS.md` |
| User corrects you | Log to `.learnings/LEARNINGS.md` with category `correction` |
| User wants missing feature | Log to `.learnings/FEATURE_REQUESTS.md` |
| API/external tool fails | Log to `.learnings/ERRORS.md` with integration details |
| Knowledge was outdated | Log to `.learnings/LEARNINGS.md` with category `knowledge_gap` |
| Found better approach | Log to `.learnings/LEARNINGS.md` with category `best_practice` |
| Simplify/Harden recurring patterns | Log/update with `Pattern-Key` for stable deduplication |
| Similar to existing entry | Link with `**See Also**`, consider priority bump |
| Broadly applicable learning | Promote to `SOUL.md`, `AGENTS.md`, or `memory/MEMORY.md` |

## Logging Format

### Learning Entry

Append to `.learnings/LEARNINGS.md`:

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: ISO-8601 timestamp
**Priority**: low | medium | high | critical
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
One-line description of what was learned

### Details
Full context: what happened, what was wrong, what's correct

### Suggested Action
Specific fix or improvement to make

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file.ext
- Tags: tag1, tag2
- See Also: LRN-20250115-001 (if related)
- Pattern-Key: simplify.dead_code | harden.input_validation (for recurring)
- Recurrence-Count: 1 (optional)
- First-Seen: 2025-01-15 (optional)
- Last-Seen: 2025-01-15 (optional)
```

### Error Entry

Append to `.learnings/ERRORS.md`:

```markdown
## [ERR-YYYYMMDD-XXX] skill_or_command_name

**Logged**: ISO-8601 timestamp
**Priority**: high
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
Brief description of what failed

### Error

Actual error message or output

```

### Context
- Command/operation attempted
- Input or parameters used
- Environment details if relevant
- Summary or redacted excerpt (avoid full transcripts)

### Suggested Fix
If identifiable, what might resolve this

### Metadata
- Reproducible: yes | no | unknown
- Related Files: path/to/file.ext
- See Also: ERR-20250115-001 (if recurring)

---
```

### Feature Request Entry

Append to `.learnings/FEATURE_REQUESTS.md`:

```markdown
## [FEAT-YYYYMMDD-XXX] capability_name

**Logged**: ISO-8601 timestamp
**Priority**: medium
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Requested Capability
What the user wanted to do

### User Context
Why they needed it, what problem they're solving

### Complexity Estimate
simple | medium | complex

### Suggested Implementation
How this could be built, what it might extend

### Metadata
- Frequency: first_time | recurring
- Related Features: existing_feature_name

---
```

## ID Generation

Format: `TYPE-YYYYMMDD-XXX`
- TYPE: `LRN` (learning), `ERR` (error), `FEAT` (feature)
- YYYYMMDD: Current date
- XXX: Sequential number (e.g., `001`, `002`)

Examples: `LRN-20250419-001`, `ERR-20250419-001`, `FEAT-20250419-001`

## Resolving Entries

When an issue is fixed, update the entry:

```markdown
**Status**: resolved

### Resolution
- **Resolved**: 2025-04-19T09:00:00Z
- **Notes**: Brief description of what was done
```

Other status values:
- `in_progress` - Actively being worked on
- `wont_fix` - Decided not to address (add reason in Resolution)
- `promoted` - Elevated to SOUL.md, AGENTS.md, or memory/MEMORY.md

## Promoting to Project Memory

When a learning is broadly applicable, promote to permanent workspace memory.

### When to Promote

- Learning applies across multiple files/features
- Knowledge any contributor should know
- Prevents recurring mistakes
- Documents project-specific conventions

### Promotion Targets

| Target | What Belongs There |
|--------|-------------------|
| `SOUL.md` | Behavioral guidelines, communication style, principles |
| `AGENTS.md` | Agent-specific workflows, tool usage patterns, delegation rules |
| `memory/MEMORY.md` | Project facts, conventions, long-term facts |

### How to Promote

1. **Distill** the learning into a concise rule or fact
2. **Add** to appropriate section in target file
3. **Update** original entry status to `promoted`

### Promotion Examples

**Learning (verbose)**:
> Project uses pnpm workspaces. Attempted `npm install` but failed. Lock file is `pnpm-lock.yaml`. Must use `pnpm install`.

**In AGENTS.md (concise)**:
```markdown
## Build & Dependencies
- Package manager: pnpm (not npm) - use `pnpm install`
```

**Learning (verbose)**:
> When modifying API endpoints, must regenerate TypeScript client. Forgetting causes type mismatches at runtime.

**In AGENTS.md (actionable)**:
```markdown
## After API Changes
1. Regenerate client: `pnpm run generate:api`
2. Check for type errors: `pnpm tsc --noEmit`
```

## Recurring Pattern Detection

When logging something similar to an existing entry:

1. **Search first**: `grep -r "keyword" .learnings/`
2. **Link entries**: Add `**See Also**: LRN-20250419-001` in Metadata
3. **Bump priority** if issue keeps recurring
4. **Consider systemic fix**: Recurring issues often indicate:
   - Missing documentation (→ promote to AGENTS.md)
   - Missing automation (→ add to AGENTS.md)

## Detection Triggers

Automatically log when you notice:

**Corrections** (→ learning with `correction`):
- "No, that's not right..."
- "Actually, it should be..."
- "You're wrong about..."
- "That's outdated..."

**Feature Requests** (→ feature request):
- "Can you also..."
- "I wish you could..."
- "Is there a way to..."
- "Why can't you..."

**Knowledge Gaps** (→ learning with `knowledge_gap`):
- User provides information you didn't know
- Documentation you referenced is outdated
- API behavior differs from your understanding

**Errors** (→ error entry):
- Command returns non-zero exit code
- Exception or stack trace
- Unexpected output or behavior

## Periodic Review

Review `.learnings/` at natural breakpoints:
- Before starting a new major task
- After completing a feature
- When working in an area with past learnings

Quick status check:
```bash
grep -h "Status\*\*: pending" .learnings/*.md | wc -l
grep -B5 "Priority\*\*: high" .learnings/*.md | grep "^## \["
```

## Priority Guidelines

| Priority | When to Use |
|----------|-------------|
| `critical` | Blocks core functionality, data loss risk, security issue |
| `high` | Significant impact, affects common workflows, recurring |
| `medium` | Moderate impact, workaround exists |
| `low` | Minor inconvenience, edge case |

## Best Practices

1. **Log immediately** - context is freshest right after the issue
2. **Be specific** - future agents need to understand quickly
3. **Include reproduction steps** - especially for errors
4. **Suggest concrete fixes** - not just "investigate"
5. **Promote aggressively** - if in doubt, add to AGENTS.md
6. **Review regularly** - stale learnings lose value