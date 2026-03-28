# ADR-003: Memory Architecture

> **Note (2026-03-28):** The mem0 backend described below was replaced by unified
> SQLite storage (see ADR-010 and `docs/memory-system-reference.md`). The data
> model (MemoryEvent, BeliefRecord) remains accurate.

## Status

Accepted — MemoryEvent model implemented (2026-03-12)

## Date

2026-03-11

## Context

The memory subsystem (`nanobot/memory/`) has evolved through several iterations:

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
   (`nanobot/memory/event.py`):

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

## Amendment: Belief State Layer (2026-03-20)

### Context

The original architecture left profile.json as a mutable dict of string lists with a
separate `meta` sidecar keyed by normalized text. This created four concrete failure modes:

1. **Metadata orphaning** — rewording a fact during consolidation loses accumulated confidence
   and evidence count (the meta key changes but the metadata stays under the old key).
2. **No provenance chain** — `evidence_count` was an integer with no link to which events
   in `events.jsonl` actually supported the belief.
3. **No supersession audit trail** — when conflicts were resolved, there was no record of
   what replaced what.
4. **MEMORY.md dual-write** — both an LLM-generated path and a deterministic `rebuild_memory_snapshot`
   could write MEMORY.md, producing inconsistent content.

### Decision

Evolve `profile.json` into a belief store rather than introducing a separate `beliefs.jsonl`
file (which would create another source of truth):

1. **Stable belief IDs** — each profile item gets a deterministic UUID (`bf-{sha1[:8]}`)
   that survives text rewording. Backfilled lazily on read (migration-on-read).

2. **Evidence linking** — `evidence_event_ids: list[str]` links each belief to its
   supporting events in `events.jsonl` (capped at 10 most recent).

3. **Supersession chains** — `supersedes_id` / `superseded_by_id` on profile metadata
   create an auditable trail when conflicts are resolved.

4. **BeliefRecord model** — a Pydantic model (`nanobot/memory/event.py`) providing
   type-safe access to profile metadata with all belief fields.

5. **Explicit mutation API** — `ProfileManager.add_belief()`, `update_belief()`,
   `retract_belief()` replace 4+ ad-hoc mutation paths with 3 well-defined methods.

6. **MEMORY.md as pure projection** — `rebuild_memory_snapshot()` is now the single writer;
   the LLM-generated `memory_update` path was removed. User-pinned sections are preserved
   via `<!-- user-pinned -->` fence markers.

7. **MemoryStore decomposition** — the 4,487-line monolith was decomposed into:
   - `ProfileManager` — belief CRUD and mutation API
   - `ConflictManager` — conflict lifecycle
   - `RetrievalPlanner` — intent classification and policy
   - `ContextAssembler` — prompt rendering
   - `EvalRunner` — evaluation and observability (CLI only)

### Alternatives rejected

- **Separate `beliefs.jsonl`** — creates another source of truth. Profile.json already has
  the bones of a belief store (confidence, status, pinned).
- **`BeliefStore` class** — unnecessary abstraction. `ProfileManager` already coordinates
  belief operations.
- **Database** — premature for current scale. JSONL files remain the persistence layer.

### Consequences

- All profile mutations now record evidence and maintain supersession trails.
- `MemoryStore` is reduced to ~3,000 lines (coordinator role only).
- mem0 is treated as a retrieval index, not a source of truth (configurable).
- Verification can assess evidence quality, not just timestamp staleness.
