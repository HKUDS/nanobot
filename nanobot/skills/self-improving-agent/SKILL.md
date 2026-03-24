---
name: self-improvement
description: "Captures learnings, errors, and corrections to enable continuous improvement. Use when: (1) A command or operation fails unexpectedly, (2) User corrects the agent, (3) User requests a capability that doesn't exist, (4) An external API or tool fails, (5) Knowledge is outdated or incorrect, (6) A better approach is discovered for a recurring task. Also review learnings before major tasks."
metadata: {"nanobot": {"always": true}}
---

# Self-Improvement Skill

Log learnings and errors to markdown files for continuous improvement. Important learnings get promoted to project memory files.

## Quick Reference

| Situation | Action |
|-----------|--------|
| Command/operation fails | Log to `.learnings/ERRORS.md` |
| User corrects you | Log to `.learnings/LEARNINGS.md` with category `correction` |
| User wants missing feature | Log to `.learnings/FEATURE_REQUESTS.md` |
| API/external tool fails | Log to `.learnings/ERRORS.md` with integration details |
| Knowledge was outdated | Log to `.learnings/LEARNINGS.md` with category `knowledge_gap` |
| Found better approach | Log to `.learnings/LEARNINGS.md` with category `best_practice` |
| Similar to existing entry | Link with `**See Also**`, consider priority bump |
| Broadly applicable learning | Promote to `AGENTS.md`, `USER.md`, or `TOOLS.md` |
| Workflow improvements | Promote to `AGENTS.md` |
| Tool gotchas | Promote to `TOOLS.md` |
| Behavioral patterns | Promote to `SOUL.md` |

## Workspace Structure

The agent injects the following workspace files into every session's system prompt:

```
~/.hiperone/workspace/
├── AGENTS.md          # Agent workflows, delegation patterns        ← auto-injected
├── SOUL.md            # Behavioral guidelines, personality          ← auto-injected
├── USER.md            # Project facts, conventions, user prefs      ← auto-injected
├── TOOLS.md           # Tool capabilities, integration gotchas      ← auto-injected
├── memory/
│   ├── MEMORY.md      # Long-term memory (consolidated facts)      ← auto-injected
│   └── HISTORY.md     # Grep-searchable session log                ← NOT injected
├── skills/            # Custom workspace skills
│   └── <name>/SKILL.md
└── .learnings/        # This skill's log files                     ← NOT injected
    ├── LEARNINGS.md   # Corrections, knowledge gaps, best practices
    ├── ERRORS.md      # Command failures, exceptions
    └── FEATURE_REQUESTS.md  # User-requested capabilities
```

**Key distinction**: Files marked `auto-injected` are loaded into the LLM system prompt on every conversation. `.learnings/` files are **not** auto-injected — they serve as a staging area. To make a learning permanent, **promote** it to one of the auto-injected files.

## Setup

The `.learnings/` directory is automatically created on first startup (`nanobot gateway` or `nanobot agent`).

If the directory is missing for any reason, create it manually:

```bash
mkdir -p ~/.hiperone/workspace/.learnings
```

## How It Works

This skill operates through two mechanisms:

1. **Error Detection Hook** (automatic): A Python hook (`SelfImprovementHook`) monitors `exec`/`shell` tool output. When it detects a crash-level error (Python exceptions, segfaults, non-zero exit codes), it appends a reminder to the tool result. You will see this as a `[self-improvement]` block after the error output — that's your cue to log the error.

2. **SKILL.md Injection** (automatic): This file is marked `always: true`, so its content is included in your system prompt every session. This teaches you when and how to log learnings.

**What is NOT automatic**: Actually writing to `.learnings/` files, reading them back, and promoting entries to bootstrap files — these all require you to use `write_file`/`read_file`/`edit_file` tools yourself.

### Promotion Targets

When learnings prove broadly applicable, promote them to workspace files:

| Learning Type | Promote To | Example |
|---------------|------------|---------|
| Behavioral patterns | `SOUL.md` | "Be concise, avoid disclaimers" |
| Workflow improvements | `AGENTS.md` | "Spawn sub-agents for long tasks" |
| Tool gotchas | `TOOLS.md` | "Git push needs auth configured first" |

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
- See Also: LRN-20250110-001 (if related to existing entry)
- Pattern-Key: simplify.dead_code | harden.input_validation (optional, for recurring-pattern tracking)
- Recurrence-Count: 1 (optional)
- First-Seen: 2025-01-15 (optional)
- Last-Seen: 2025-01-15 (optional)

---
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
```
Actual error message or output
```

### Context
- Command/operation attempted
- Input or parameters used
- Environment details if relevant

### Suggested Fix
If identifiable, what might resolve this

### Metadata
- Reproducible: yes | no | unknown
- Related Files: path/to/file.ext
- See Also: ERR-20250110-001 (if recurring)

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
- XXX: Sequential number or random 3 chars (e.g., `001`, `A7B`)

## Resolving Entries

When an issue is fixed, update the entry:

1. Change `**Status**: pending` → `**Status**: resolved`
2. Add resolution block after Metadata:

```markdown
### Resolution
- **Resolved**: 2025-01-16T09:00:00Z
- **Commit/PR**: abc123 or #42
- **Notes**: Brief description of what was done
```

Other status values:
- `in_progress` - Actively being worked on
- `wont_fix` - Decided not to address (add reason in Resolution notes)
- `promoted` - Elevated to AGENTS.md, USER.md, or TOOLS.md

## Promoting to Project Memory

When a learning is broadly applicable (not a one-off fix), promote it to permanent project memory.

### When to Promote

- Learning applies across multiple files/features
- Knowledge any contributor (human or AI) should know
- Prevents recurring mistakes
- Documents project-specific conventions

### Promotion Targets

| Target | What Belongs There |
|--------|-------------------|
| `USER.md` | Project facts, conventions, gotchas |
| `AGENTS.md` | Agent-specific workflows, tool usage patterns, automation rules |
| `SOUL.md` | Behavioral guidelines, communication style, principles |
| `TOOLS.md` | Tool capabilities, usage patterns, integration gotchas |

### How to Promote

1. **Distill** the learning into a concise rule or fact
2. **Add** to appropriate section in target file (create file if needed)
3. **Update** original entry status to `promoted`

### Promotion Examples

**Learning** (verbose, in `.learnings/ERRORS.md`):
> 调用飞书审批 API 时传了 user_id 格式的 ID，API 返回 "user id not found"。
> 必须传 open_id 格式（ou_xxx），不能传 user_id。

**Promoted to `TOOLS.md`** (concise):
```markdown
## 飞书审批 API
- user_id 参数必须传 open_id 格式（ou_xxx），不支持 user_id
```

**Learning** (verbose, in `.learnings/LEARNINGS.md`):
> 用户说"调休 明天上午"时，需要自动计算 RFC3339 格式的时间。
> 之前直接拼字符串导致时区错误，应该用 datetime 库。

**Promoted to `AGENTS.md`** (actionable):
```markdown
## 时间处理
- 所有飞书 API 时间参数必须为 RFC3339 格式，带时区偏移（+08:00）
- 用 datetime 库计算，不要手动拼字符串
```

### Promotion Rule (Recurring Patterns)

Promote recurring patterns when all are true:
- `Recurrence-Count >= 3`
- Seen across at least 2 distinct tasks
- Occurred within a 30-day window

Write promoted rules as short prevention rules (what to do before/while coding), not long incident write-ups.

## Recurring Pattern Detection

If logging something similar to an existing entry:

1. **Search first**: `grep -r "keyword" .learnings/`
2. **Link entries**: Add `**See Also**: ERR-20250110-001` in Metadata
3. **Bump priority** if issue keeps recurring
4. **Consider systemic fix**: Recurring issues often indicate:
   - Missing documentation (promote to USER.md)
   - Missing automation (add to AGENTS.md)
   - Architectural problem (create tech debt ticket)

## Simplify & Harden Feed

Use this workflow to ingest recurring patterns from the `simplify-and-harden`
skill and turn them into durable prompt guidance.

### Ingestion Workflow

1. Read `simplify_and_harden.learning_loop.candidates` from the task summary.
2. For each candidate, use `pattern_key` as the stable dedupe key.
3. Search `.learnings/LEARNINGS.md` for an existing entry with that key:
   - `grep -n "Pattern-Key: <pattern_key>" .learnings/LEARNINGS.md`
4. If found:
   - Increment `Recurrence-Count`
   - Update `Last-Seen`
   - Add `See Also` links to related entries/tasks
5. If not found:
   - Create a new `LRN-...` entry
   - Set `Source: simplify-and-harden`
   - Set `Pattern-Key`, `Recurrence-Count: 1`, and `First-Seen`/`Last-Seen`

### Promotion Rule (System Prompt Feedback)

Promote recurring patterns into agent context/system prompt files when all are true:

- `Recurrence-Count >= 3`
- Seen across at least 2 distinct tasks
- Occurred within a 30-day window

Promotion targets:
- `USER.md`
- `AGENTS.md`
- `SOUL.md` / `TOOLS.md` for workspace-level guidance when applicable

Write promoted rules as short prevention rules (what to do before/while coding),
not long incident write-ups.

## Periodic Review

Review `.learnings/` at natural breakpoints:

### When to Review
- Before starting a new major task
- After completing a feature
- When working in an area with past learnings
- Weekly during active development

### Quick Status Check
```bash
# Count pending items
grep -h "Status\*\*: pending" .learnings/*.md | wc -l

# List pending high-priority items
grep -B5 "Priority\*\*: high" .learnings/*.md | grep "^## \["

# Find learnings for a specific area
grep -l "Area\*\*: backend" .learnings/*.md
```

### Review Actions
- Resolve fixed items
- Promote applicable learnings
- Link related entries
- Escalate recurring issues

## Detection Triggers

Automatically log when you notice:

**Corrections** (→ learning with `correction` category):
- "No, that's not right..."
- "Actually, it should be..."
- "You're wrong about..."
- "That's outdated..."

**Feature Requests** (→ feature request):
- "Can you also..."
- "I wish you could..."
- "Is there a way to..."
- "Why can't you..."

**Knowledge Gaps** (→ learning with `knowledge_gap` category):
- User provides information you didn't know
- Documentation you referenced is outdated
- API behavior differs from your understanding

**Errors** (→ error entry):
- Command returns non-zero exit code
- Exception or stack trace
- Unexpected output or behavior
- Timeout or connection failure

## Priority Guidelines

| Priority | When to Use |
|----------|-------------|
| `critical` | Blocks core functionality, data loss risk, security issue |
| `high` | Significant impact, affects common workflows, recurring issue |
| `medium` | Moderate impact, workaround exists |
| `low` | Minor inconvenience, edge case, nice-to-have |

## Area Tags

| Area | Scope |
|------|-------|
| `frontend` | UI, components, client-side code |
| `backend` | API, services, server-side code |
| `infra` | CI/CD, deployment, Docker, cloud |
| `tests` | Test files, testing utilities, coverage |
| `docs` | Documentation, comments, READMEs |
| `config` | Configuration files, environment, settings |

## Automatic Skill Extraction

When a learning is valuable enough to become a reusable skill, extract it.

### Skill Extraction Criteria

| Criterion | Description |
|-----------|-------------|
| **Recurring** | Has `See Also` links to 2+ similar issues |
| **Verified** | Status is `resolved` with working fix |
| **Non-obvious** | Required actual debugging/investigation to discover |
| **Broadly applicable** | Not project-specific; useful across codebases |
| **User-flagged** | User says "save this as a skill" or similar |

### Extraction Workflow

1. **Identify candidate**: Learning meets extraction criteria
2. **Create skill directory**: `skills/<skill-name>/SKILL.md`
3. **Customize SKILL.md**: Fill in with learning content (YAML frontmatter with `name` and `description`)
4. **Update learning**: Set status to `promoted_to_skill`, add `Skill-Path`
5. **Verify**: Ensure the skill is self-contained

## Gitignore Options

**Keep learnings local** (per-developer):
```gitignore
.learnings/
```

**Track learnings in repo** (team-wide):
Don't add to .gitignore - learnings become shared knowledge.

**Hybrid** (track templates, ignore entries):
```gitignore
.learnings/*.md
!.learnings/.gitkeep
```

## Best Practices

1. **Log immediately** - context is freshest right after the issue
2. **Be specific** - future agents need to understand quickly
3. **Include reproduction steps** - especially for errors
4. **Link related files** - makes fixes easier
5. **Suggest concrete fixes** - not just "investigate"
6. **Use consistent categories** - enables filtering
7. **Promote aggressively** - if in doubt, promote to USER.md
8. **Review regularly** - stale learnings lose value
