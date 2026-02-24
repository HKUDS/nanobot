---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` -- Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` -- Append-only event log. NOT loaded into context. Search it with grep.

## Search Past Events

```bash
grep -i "keyword" memory/HISTORY.md
```

Use the `exec` tool to run grep. Combine patterns: `grep -iE "meeting|deadline" memory/HISTORY.md`

## When to Update MEMORY.md

Write important, recurring facts using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

Be conservative -- only save facts the user would expect you to know next time. Don't save casual one-off mentions or things said once in passing.

Do not tell the user you've written to memory. Just do it silently.

## Honcho

If Honcho memory is active, it handles long-term persistence automatically from conversations. You don't need to write to MEMORY.md for facts Honcho already captures.

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.
