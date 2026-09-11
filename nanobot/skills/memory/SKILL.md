---
name: memory
description: Search conversation history and understand Dream-managed profile and memory files.
---

# Memory

## Structure

- `SOUL.md` — Bot personality and communication style. **Managed by Dream.**
- `USER.md` — User profile and preferences. **Managed by Dream.**
- `memory/MEMORY.md` — Long-term facts (project context, important events). **Managed by Dream.**
- `memory/history.jsonl` — append-only JSONL, not loaded into context. Prefer the
  built-in `grep` tool to search it.

## Search Past Events

Use the `History log` path shown in the system prompt. Always pass it to `grep`;
never substitute a different project-relative `memory/history.jsonl`, which may belong
to the selected project. Each JSONL line contains `cursor`, `timestamp`, and `content`.

- For broad searches, start with `output_mode="count"` or the default
  `files_with_matches` mode before expanding to full content
- Use `output_mode="content"` plus `context_before` / `context_after` when you need the exact matching lines
- Use `fixed_strings=true` for literal timestamps or JSON fragments
- Use `head_limit` / `offset` to page through long histories

Examples (replace `<history-log-path>` with the path from the system prompt):
- `grep(pattern="keyword", path="<history-log-path>", case_insensitive=true)`
- `grep(pattern="2026-04-02 10:00", path="<history-log-path>", fixed_strings=true)`
- `grep(pattern="keyword", path="<history-log-path>", output_mode="count", case_insensitive=true)`
- `grep(pattern="oauth|token", path="<history-log-path>", output_mode="content", case_insensitive=true)`

## Important

- During ordinary conversations, do not edit SOUL.md, USER.md, or memory/MEMORY.md. Leave updates and corrections to Dream.
- During a Dream memory-consolidation task, update these files with the supplied file tools, including correcting outdated information in the current run.
- Users can view Dream's activity with the `/dream-log` command.
