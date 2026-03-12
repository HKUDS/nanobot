# ADR-003: Memory Architecture

## Status

Accepted — MemoryEvent model implemented (2026-03-12)

## Date

2026-03-11

## Context

The memory subsystem (`nanobot/agent/memory/`) has evolved through several iterations:

1. **V1** — Simple `MEMORY.md` + `HISTORY.md` text files with grep-based retrieval.
2. **V2 (current)** — Hybrid approach: structured events in `events.jsonl`, user profile in
   `profile.json`, active knowledge snapshot in `MEMORY.md`, with mem0 vector store as
   primary retrieval backend and local BM25 as fallback.

The current architecture is documented in `docs/memory-architecture-proposal.md` and
`docs/memory-semantic-episodic-separation-plan-2026-03-01.md`.

Key challenge: memory events are currently passed as raw `dict` objects through the system,
making it easy to introduce inconsistencies.

## Decision

1. **Retain the mem0-first strategy with local fallback.** This provides vector-based
   semantic retrieval when available, with deterministic keyword fallback otherwise.

2. **Introduce typed `MemoryEvent` model.** Replace raw dicts with a Pydantic model
   (`nanobot/agent/memory/event.py`):

   ```python
   class MemoryEvent(BaseModel):
       id: str = ""
       timestamp: str = ""
       channel: str = ""
       chat_id: str = ""
       type: EventType = "fact"          # preference|fact|task|decision|constraint|relationship
       summary: str                      # required, non-empty
       entities: list[str] = []
       salience: float = 0.6            # 0.0–1.0
       confidence: float = 0.7          # 0.0–1.0
       source_span: list[int] = []
       ttl_days: int | None = None
       memory_type: MemoryType = "episodic"  # semantic|episodic|reflection
       topic: str = ""
       stability: Stability = "medium"  # high|medium|low
       source: str = "chat"
       evidence_refs: list[str] = []
       status: str | None = None
       metadata: dict[str, Any] = {}
       triples: list[KnowledgeTriple] = []
       # Supersession tracking
       canonical_id: str = ""
       supersedes_event_id: str = ""
       supersedes_at: str = ""
   ```

3. **Write path**: `MemoryExtractor` produces `list[MemoryEvent]` → `MemoryStore.append_events()`
   validates and persists to both mem0 and `events.jsonl`.

4. **Read path**: `MemoryStore.retrieve(query)` → mem0 first → local fallback →
   optional cross-encoder re-ranking → returns `list[MemoryEvent]`.

5. **Consolidation** remains a periodic background task triggered per-session.

6. **No external database** (Postgres, Redis) for now. JSONL + JSON files are appropriate
   for current scale. Revisit if event volume exceeds ~10k per workspace.

## Consequences

### Positive

- Typed events catch schema errors at write time instead of silent corruption.
- Clear contract between extractor, store, and retrieval.
- Deterministic fallback ensures memory works without mem0/vector store.

### Negative

- Migration needed for existing `events.jsonl` files (add type validation).
- Pydantic model adds a small serialization overhead per event.

### Neutral

- `events.jsonl` remains append-only — no migration of existing data required, only
  validation of new writes.
- `MEMORY.md` snapshot format unchanged.
