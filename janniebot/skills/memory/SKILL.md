---
name: memory
description: Two-layer memory system with Dream-managed knowledge files.
always: true
---

# Memory

## Structure

- `SOUL.md` — Bot personality and communication style. **Managed by Dream.** Do NOT edit.
- `USER.md` — User profile and preferences. **Managed by Dream.** Do NOT edit.
- `memory/MEMORY.md` — Long-term facts (project context, important events). **Managed by Dream.** Do NOT edit.
- `memory/history.jsonl` — append-only JSONL, not loaded into context. search with `jq`-style tools.

## Search Past Events

`memory/history.jsonl` is JSONL format — each line is a JSON object with `cursor`, `timestamp`, `content`.

Examples (replace `keyword`):
- **Python (cross-platform):** `python -c "import json; [print(json.loads(l).get('content','')) for l in open('memory/history.jsonl','r',encoding='utf-8') if l.strip() and 'keyword' in l.lower()][-20:]"`
- **jq:** `cat memory/history.jsonl | jq -r 'select(.content | test("keyword"; "i")) | .content' | tail -20`
- **grep:** `grep -i "keyword" memory/history.jsonl`

## Important

- **Do NOT edit SOUL.md, USER.md, or MEMORY.md.** They are automatically managed by Dream.
- If you notice outdated information, it will be corrected when Dream runs next.
- Users can view Dream's activity with the `/dream-log` command.
