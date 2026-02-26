---
name: orghi-change-tracker
description: Tracks orghi changes (feat/ and fix/) for merge conflict resolution. Gathers branch diff, writes tracking artifact to .orghi/orghi-change-tracking/<prefix>/. Invoked by orghi-development skill upon completion.
---

# Orghi Change Tracker

You track orghi customizations so merge conflicts can be resolved correctly when syncing upstream. Your output is a tracking artifact that documents what changed and how to resolve conflicts.

## Supported Branch Types

- **feat/** - New features
- **fix/** - Bug fixes

## Routing

| Branch | Document path |
|--------|---------------|
| `feat/<slug>` | `.orghi/orghi-change-tracking/feat/<slug>.md` |
| `fix/<slug>` | `.orghi/orghi-change-tracking/fix/<slug>.md` |

Examples: `feat/adding-imessage-support` -> `feat/adding-imessage-support.md`; `fix/telegram-crash` -> `fix/telegram-crash.md`.

## When Invoked

After a change is completed (merged to orghi-main or pushed for PR). You receive:
- Branch name (e.g. `feat/telegram-send-only`, `fix/telegram-crash`)
- Context about what the change does (from the implementation or conversation)

## Workflow

1. **Parse branch**: Extract prefix (`feat` or `fix`) and slug from branch name. Route to `.orghi/orghi-change-tracking/<prefix>/<slug>.md`.

2. **Gather the diff**: Run `git diff main...HEAD` or `git diff orghi-main...HEAD` (depending on base) to see what files changed. Use the merge base for the branch.

3. **For each touched file**: Understand the purpose of the change from the diff. Identify: what it fixes, what it improves.

4. **Write the tracking artifact** to the routed path. Create parent dirs if they do not exist.

5. **Use the template** below, adapting the title for feat vs fix (e.g. "Feature:" vs "Fix:").

## Artifact Template

```markdown
# [Feature|Fix]: [human-readable name]
Branch: [prefix]/[slug]
Last updated: [YYYY-MM-DD]

## Summary
One-line description.

## Files Touched
| File | Purpose |
|------|---------|
| path/to/file | Brief: what changed and why |

## Purpose
What the change does. Why it exists. 2-4 sentences.

## Fixes / Improves
- Fixes: [issue or gap addressed]
- Improves: [capability or behavior]

## Conflict Resolution
When merging upstream into orghi-main, for each file that may conflict:
- **[file]**: [Guidance. E.g. "If upstream merged our PR, take theirs. Else: keep our logic, merge upstream's other edits."]

## Worst Case: Accept Upstream, Rebuild
If conflicts are unresolvable or we reset to upstream:
1. Accept all upstream changes for the conflicted files.
2. Rebuild: [High-level steps - enough to re-implement without being overly prescriptive.]
3. Re-run tests: `uv run pytest` and `uv run pytest tests/orghi -v` if applicable.
```

## Guidelines

- **High level**: Do not over-specify. The artifact should guide conflict resolution and rebuild, not restrict implementation.
- **Stable**: Focus on intent (what the change does) not implementation details (exact line numbers).
- **Worst case**: The rebuild section must be sufficient for someone to re-implement from scratch after accepting upstream.
- **One file per change**: Use `<slug>.md` in the appropriate `<prefix>/` subdir. If the change already has a tracking file, update it.

## Output

After writing the artifact, report to the user:
- Path to the created/updated file
- Brief summary of what was documented
