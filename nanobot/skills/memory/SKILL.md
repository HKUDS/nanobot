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

**Recommended approach (cross-platform):**
- Use `read_file` to read `memory/HISTORY.md`, then search in-memory
- This is the most reliable and portable method on all platforms

**Alternative (if you need command-line search):**
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Python (cross-platform):** `python -c "import re; content=open('memory/HISTORY.md', encoding='utf-8').read(); print('\n'.join([l for l in content.split('\n') if 'keyword' in l.lower()][-20:]))"`

Use the `exec` tool to run these commands. For complex searches, prefer `read_file` + in-memory filtering.

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.
