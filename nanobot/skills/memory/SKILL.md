---
name: memory
description: Three-layer memory system with skill extraction and grep-based recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep-style tools or in-memory filters. Each entry starts with [YYYY-MM-DD HH:MM] .
- `memory/SKILLS.jsonl` — Learned workflow patterns auto-extracted from successful multi-step tasks. Relevant skills are loaded into your context based on the current query.

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

## Learned Skills

When you see a relevant skill in your context under "Learned Skills", use it as a reference to guide your approach. Skills are abstract workflow templates — adapt specific steps to the current task.

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. Successful multi-step workflows are extracted to SKILLS.jsonl. You don't need to manage this.
