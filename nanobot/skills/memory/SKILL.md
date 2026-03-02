---
name: memory
description: Semantic + episodic memory system with BM25 + temporal decay ranked recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term semantic memory: stable facts (preferences, relationships, projects). Always loaded into your context.
- `memory/memory.jsonl` — Long-term episodic memory: time-bound events and context. Top-5 most relevant auto-injected per turn using BM25 + temporal decay ranking.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep. Each entry starts with [YYYY-MM-DD HH:MM].

## Search Past Events

```bash
grep -i "keyword" memory/HISTORY.md
```

Use the `exec` tool to run grep. Combine patterns: `grep -iE "meeting|deadline" memory/HISTORY.md`

## When to Update MEMORY.md

Write semantic facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Relationships ("Alice is the project lead")

## When to Update memory.jsonl

Write episodic facts immediately using `edit_file` or `write_file`:

```json
{"text": "The API uses OAuth2", "importance": "medium", "created_at": "2026-01-01T10:00:00"}
{"text": "I am traveling next week", "importance": "high", "created_at": "2026-01-01T10:00:00"}
```
- `importance` — retrieval priority: `high`=must remember, `medium`=useful, `low`=nice to have

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.
