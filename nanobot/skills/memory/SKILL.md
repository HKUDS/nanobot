---
name: memory
description: Structured fact store with semantic retrieval and token-budgeted context.
always: true
---

# Memory

## Architecture

Memory is a **three-layer system** backed by SQLite:

| Layer | Storage | Loaded into context? |
|-------|---------|---------------------|
| **FactStore** (`memory.db`) | Discrete facts with category, token count, and optional vector embedding | Top-k relevant facts injected automatically each turn |
| **HISTORY.md** + `history_entries` table | Append-only event log with timestamps | Not loaded by default; searched on demand via BM25S or grep |
| **Rolling summary** | LLM-compressed summary of older conversation turns | Injected when conversation exceeds the token budget |

`MEMORY.md` is auto-exported from the FactStore as a human-readable snapshot. Do **not** edit it manually — it will be overwritten on the next consolidation.

## How Facts Are Retrieved

Each message triggers retrieval of the most relevant stored facts:

1. **KNN vector search** — if NVIDIA NIM embeddings are configured, the user's message is embedded and matched against stored fact vectors using cosine similarity.
2. **BM25S keyword search** — lightweight local fallback using keyword matching (always available if `bm25s` is installed).
3. **Recency fallback** — if neither is available, the most recently added facts are returned.

Results are capped by a token budget so they never overflow the LLM context window.

## Searching Past Events

Use the `exec` tool to search the history log:

```bash
grep -i "keyword" memory/HISTORY.md
```

Combine patterns: `grep -iE "meeting|deadline" memory/HISTORY.md`

History entries are also indexed in SQLite and searched via BM25S when building context.

## Auto-consolidation

When a conversation ends or grows large, an LLM pass automatically:

1. **Extracts discrete facts** — each tagged with a category (`preference`, `contact`, `project`, `learning`, `system`, `general`) and stored in the FactStore via the `save_facts` tool.
2. **Writes a history entry** — a timestamped paragraph summarizing key events, appended to both `HISTORY.md` and the `history_entries` table.
3. **Deduplicates** — new facts are checked against existing ones to avoid redundancy.
4. **Embeds** — if NIM is enabled, new facts are embedded with `input_type="passage"` for later KNN retrieval.

## Rolling Summary (Progressive Compression)

When conversation history exceeds the configured token budget:

1. Older turns beyond a recent window are compressed into a rolling summary by the LLM.
2. The summary is stored in session metadata and prepended to the conversation on subsequent turns.
3. This keeps the full context available to the LLM without exceeding token limits.

## When to Save Facts Manually

Auto-consolidation handles most cases, but you can write important facts immediately using `edit_file` or `write_file` on `memory/MEMORY.md` if the user explicitly asks you to remember something right now. These will be picked up by the FactStore on next restart via auto-seeding.

## Configuration

Memory behavior is controlled in `config.json` under the `memory` key:

```json
{
  "memory": {
    "embedding": {
      "enabled": true,
      "model": "nvidia/nv-embedqa-e5-v5"
    },
    "token_budget": {
      "system": 1500,
      "memory": 500,
      "conversation": 0
    }
  }
}
```

Embedding can also be configured via environment variables: `NIM_API_KEY`, `NIM_BASE_URL`, `NIM_MODEL`.
