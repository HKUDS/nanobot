# RAM-first Memory Checkpoint Design

## Why this design

nanobot is intentionally lightweight. This design keeps memory fast and simple by making the hot path in-memory and moving disk writes to checkpoint events.

## Goals

- Keep turn-time memory access in RAM
- Preserve long-term memory across restarts
- Avoid embedding/vector dependencies
- Keep implementation small and easy to audit

## Non-goals

- Perfect semantic recall for arbitrary text
- Distributed memory sync across multiple nodes
- Heavy retrieval pipelines

## Architecture

The runtime is split into three layers:

1. Short-term working memory (RAM only)
- Per-session turn window
- Per-session pending item queue
- Used for immediate continuity

2. Long-term snapshot memory (RAM-first)
- In-memory long-term items are updated during turns
- Persisted to `memory/LTM_SNAPSHOT.json` on checkpoint
- Optional audit append log at `memory/LTM_AUDIT.jsonl`

2.5. Self-improvement lessons (RAM-first)
- In-memory lessons are learned from tool failures and user corrections
- Persisted to `memory/LESSONS.jsonl` on checkpoint
- Optional lesson audit log at `memory/LESSONS_AUDIT.jsonl`

3. Session log storage (append-only)
- Conversation messages append to `~/.nanobot/sessions/*.jsonl`
- Periodic compaction rewrites to keep only recent history

## Data model

Long-term snapshot item:

```json
{
  "id": "ltm_1739443200123_1",
  "text": "User prefers concise Chinese replies",
  "source": "explicit_user",
  "session_key": "telegram:12345",
  "created_at": "2026-02-13T09:01:10.223000",
  "updated_at": "2026-02-13T09:05:40.119000",
  "hits": 2
}
```

## Write path

On each turn:

1. Update short-term ring buffer in RAM
2. Detect explicit memory intents (e.g. `记住...`, `remember ...`)
3. Upsert long-term snapshot item in RAM
4. Flush when one of these triggers:
- dirty updates >= `flushEveryUpdates`
- elapsed time >= `flushIntervalSeconds`
- explicit immediate flush (stronger durability)
- process stop

## Read path

During prompt build:

1. Read long-term snapshot items from RAM
2. Read top self-improvement lessons from RAM
3. Add legacy `MEMORY.md` notes (human-readable)
4. Add short-term working memory and pending items for current session

This keeps read latency constant and avoids per-turn disk reads for long-term state.

## Durability semantics

- Normal memory updates: eventual durability (checkpointed)
- Explicit memory updates: immediate flush path
- Crash window: up to checkpoint interval for non-immediate updates

## Compaction strategy

Long-term snapshot compaction:

- Deduplicate by normalized text
- Keep newest items first
- Enforce max item cap

Session compaction:

- Triggered by message count or file size threshold
- Rewrites session file with metadata + recent N messages only

## Failure behavior

- Corrupt snapshot file: fallback to empty RAM state for this run
- Audit write failure: does not block core agent loop
- Session file growth: bounded by periodic compaction

## Why no embeddings

This design avoids embedding/vector systems to preserve nanobot's lightweight footprint and operational simplicity:

- No extra service dependencies
- No vector index build/maintenance cost
- Deterministic and inspectable memory behavior

## Operational commands

```bash
nanobot memory status
nanobot memory flush
nanobot memory compact --max-items 300
nanobot memory lessons status
nanobot memory lessons compact --max-lessons 200
nanobot memory lessons reset --yes
nanobot session compact --all
```
