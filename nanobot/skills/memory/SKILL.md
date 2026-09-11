---
name: memory
description: Search past conversations in the agent's history log.
---

# Memory

## Search Past Events

Search the exact `History log` path from the system prompt with `grep`; a project-relative
`memory/history.jsonl` may belong to a different workspace. The log is append-only JSONL,
with `cursor`, `timestamp`, and `content` per entry, and is not loaded into context.

Start broad searches with `output_mode="count"`, then narrow by topic or date and request
matching content. Use `fixed_strings=true` for literal timestamps or JSON fragments.
Page long results with `head_limit` / `offset` and use `context_before` / `context_after`
when nearby entries matter.

Example (replace `<history-log-path>` with the path from the system prompt):
`grep(pattern="project-name", path="<history-log-path>", output_mode="content", case_insensitive=true, head_limit=20)`

Use `/dream-log` to view Dream's memory changes.
