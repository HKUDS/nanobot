---
name: memory
description: Multi-layer memory system with Dream-managed knowledge files and structured entity/knowledge/journal hierarchy.
always: true
---

# Memory

## Structure

### Core files (Dream-managed — do NOT edit directly)
- `SOUL.md` — Bot personality and operating rules.
- `USER.md` — User profile and preferences.
- `memory/MEMORY.md` — Hub: active context, pending items, entity map. Keep under 150 lines.
- `memory/history.jsonl` — Append-only conversation log.

### Entity files (update immediately when new entities appear)
- `memory/entities/PEOPLE.md` — People mentioned: name, role, relationship, notes.
- `memory/entities/COMPANIES.md` — Companies: name, domain, relationship to Alessandro.
- `memory/entities/PROJECTS.md` — Projects: status, decisions, path, links.

### Knowledge files (update when system/infra facts are learned)
- `memory/knowledge/SYSTEMS.md` — Infrastructure paths, services, credentials structure, constraints.

### Transient / time-based
- `memory/scribble/` — Raw context captures (1-2 lines). Processed daily at 06:00 by scribacchino-context-digest.
- `memory/journal/YYYY-MM-DD.md` — Daily log of significant decisions and events.

---

## When to write

| Event | Action |
|-------|--------|
| New person mentioned | Add to `memory/entities/PEOPLE.md` immediately |
| New company mentioned | Add to `memory/entities/COMPANIES.md` immediately |
| Project decision or status change | Update `memory/entities/PROJECTS.md` |
| System path / infra / credential structure | Update `memory/knowledge/SYSTEMS.md` |
| Decision made | Add to today's journal + update MEMORY.md if pending |
| Task completed | Remove from MEMORY.md pending |
| Context switch imminent | Append raw note to today's scribble file |

---

## Search Past Events

`memory/history.jsonl` is JSONL — each line has `cursor`, `timestamp`, `content`.

- Broad search: `grep(pattern="keyword", path="memory", glob="*.jsonl", output_mode="count")`
- Exact match: `grep(pattern="keyword", path="memory/history.jsonl", fixed_strings=true)`
- Content preview: `grep(pattern="keyword", path="memory/history.jsonl", output_mode="content", context_after=2)`

---

## Important

- **Do NOT edit SOUL.md, USER.md, or MEMORY.md directly.** They are managed by Dream.
- Entity and knowledge files ARE writable by the agent — update them proactively.
- If outdated info is noticed, correct it immediately in the appropriate file.
- Dream runs every hour and consolidates memory automatically.
