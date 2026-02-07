# MemoryBox (Nanobot Tool)

MemoryBox is a small, auditable memory layer for Nanobot: **Markdown is the source of truth**, and **SQLite (FTS5 if available)** provides fast recall. Designed to be simple, reversible (soft-delete), and easy to inspect in a Git repo.

## What it does
- Stores short memory items (note/fact/todo/decision/pref)
- Extracts lightweight semantics from text:
  - `#tags` and `@people`
- Supports:
  - `remember` / `recall` / `soft_forget` / `restore` / `promote`
- Uses stable short ids like `^a1b2c3d4e5`

## On-disk layout
Given a workspace `<ws>`:
- `<ws>/memory/YYYY-MM-DD.md` — daily append-only log
- `<ws>/memory/MEMORY.md` — curated long-term memory
- `<ws>/memory/.trash/YYYY-MM-DD.md` — soft-deleted items (restorable)
- `<ws>/memory/index.sqlite3` — SQLite index (`mem`, `trash`, optional `*_fts`)

## Query mini-syntax
Accepted by `MemoryStore.recall()`:
- Filters:
  - `kind:fact|pref|decision|todo|note`
  - `scope:daily|long|pinned` (pinned treated as `long`)
- Semantics:
  - `#tag` and `@person`
- Anything else is free-text.

Examples:
- `kind:todo #groceries buy eggs`
- `scope:long @alex meeting notes`
- `#travel @sam itinerary`

## FTS behavior
- If SQLite FTS5 is available: recall/search uses `MATCH` + `bm25()` ranking.
- If not available: recall falls back to scanning Markdown files.


## Quick benchmark
Run a local benchmark (writes, promotes, retrieval quality, neg controls, forget/restore invariants).

> Run from the repo root (do **not** run from inside `nanobot/agent/tools/smriti/` to avoid stdlib `types` shadowing).
And `smriti` should be in `/docker/nanobot/nanobot/agent/tools/`

```bash
cd <PATH TO NANOBOT> # i.e. from repo root
python -m nanobot.agent.tools.smriti.bench \
  --workspace /tmp/smriti_bench \
  --items 2000 --queries 400 --seed 0 \
  --k 5 --neg_frac 0.40 --promote_frac 0.05 \
  --clean
```
## Credits
AI Co-authors: OpenAI GPT-5.2, Google Gemini.<br>
AI Model Testing: Kivi K2.5
