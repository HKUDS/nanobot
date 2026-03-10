---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep-style tools or in-memory filters. Each entry starts with [YYYY-MM-DD HH:MM].

## Search Past Events

Choose the search method based on file size:

- Small `memory/HISTORY.md`: use `read_file`, then search in-memory
- Large or long-lived `memory/HISTORY.md`: use the `exec` tool for targeted search

Examples:
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Cross-platform Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

Prefer targeted command-line search for large history files.

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.

## Cross-Instance Memory Migration

Use the `memory_migrate` tool to read memory from other nanobot instances on the same machine.

### Usage

- **List instances:** `memory_migrate(source_instance="list")` — discover all instances and their sharing status.
- **Read memory:** `memory_migrate(source_instance="main", query="feishu group filter", scope="all")` — fetch relevant memory from the target instance.
- **Scope options:** `memory` (MEMORY.md only), `history` (HISTORY.md only), `sessions` (conversation logs), `skills` (skill definitions), `all` (everything).

### Behavior

- The tool only **reads** from the target instance. You decide what to save into your own MEMORY.md.
- Each instance can configure `memorySharing` in its config.json to control access:
  - `enabled: false` — no one can read this instance's memory.
  - `allowFrom: ["instanceA", "instanceB"]` — only listed instances can read (whitelist).
  - `enabled: true` with empty `allowFrom` — open to all instances.
- You cannot read your own memory via this tool (use `read_file` instead).

### Sessions

- Use `scope="sessions"` to access conversation session logs.
- Without `session_id`, lists all available session files.
- With `session_id`, reads messages from that session (supports partial filename match).
- The `query` parameter filters messages by keyword.

### Skills

- Use `scope="skills"` to access skill definitions.
- Without `skill_name`, lists all available skills.
- With `skill_name`, reads the full SKILL.md and reference files for that skill.
