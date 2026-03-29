---
name: memory
description: Three-layer memory system with semantic search.
always: true
---

# Memory

## Structure

```
memory/
├── MEMORY.md   ← Long-term facts (always loaded)
├── TACIT.md    ← How you operate (always loaded)
├── HISTORY.md  ← Event log (grep + semantic search)
└── vectordb/   ← ChromaDB for semantic search
```

## Layers

| Layer | Loaded? | Purpose | Example |
|-------|---------|---------|---------|
| **MEMORY.md** | ✅ Always | Facts about the world | "User lives in Abu Dhabi" |
| **TACIT.md** | ✅ Always | How user operates | "Prefers tables, concise answers" |
| **HISTORY.md** | ❌ Search | What happened | "[2026-02-24] Discussed BTC backtest" |
| **vectordb/** | ❌ Search | Semantic index | Embeddings for similarity search |

## Search Past Events

### Semantic Search (Recommended)

Use the `memory_search` tool for natural language queries:

```
memory_search("crypto trading discussion")
memory_search("SSD purchase")
memory_search("restaurant recommendations")
```

### Keyword Search (Fallback)

```bash
grep -i "keyword" memory/HISTORY.md
grep -iE "meeting|deadline" memory/HISTORY.md
```

## Reindex Vector Store

If search results seem stale or after manually editing HISTORY.md:

```
memory_reindex
```
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

## When to Update TACIT.md

Update when you learn how the user operates:
- Communication style preferences
- Work patterns and schedules
- Lessons learned from past interactions
- Security rules and constraints

## Auto-consolidation

Old conversations are automatically:
1. Summarized and appended to HISTORY.md
2. Indexed into vectordb for semantic search
3. Long-term facts extracted to MEMORY.md

## Requirements

- **ChromaDB** (optional): `pip install chromadb`
  - Enables semantic search via `memory_search` tool
  - Falls back to grep if not installed
  - Uses all-MiniLM-L6-v2 embeddings (runs on CPU or GPU)
