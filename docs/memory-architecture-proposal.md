# Nanobot Memory Upgrade Proposal (2026-02-24)

## 1) Current State (from code)

- Memory layers today:
  - `memory/MEMORY.md` (always injected into system prompt)
  - `memory/HISTORY.md` (append-only log, grep retrieval by the agent)
- Consolidation is triggered by message count (`memory_window`) and performed by one LLM tool call (`save_memory`) in `nanobot/agent/memory.py`.
- Session history remains append-only for cache efficiency (`nanobot/session/manager.py`), with `last_consolidated` used to avoid reprocessing.

This baseline is strong and simple, but it has 3 limitations:

1. Retrieval quality depends on exact keywords in `HISTORY.md`.
2. No explicit memory typing (facts/preferences/tasks/decisions).
3. No objective memory quality feedback loop (precision/recall, contradiction, staleness).

---

## 2) Target Architecture (Hybrid, backward compatible)

Keep the current markdown memory as human-readable source of truth, and add a structured memory index for retrieval and quality control.

### Layer A — Episodic event store (structured)

- New file: `memory/events.jsonl`
- One JSON record per notable turn/event.
- Suggested schema:
  - `id`, `timestamp`, `channel`, `chat_id`
  - `type` (`preference|fact|task|decision|constraint|relationship`)
  - `summary` (1-2 sentences)
  - `entities` (people/projects/files/tools)
  - `salience` (0..1)
  - `confidence` (0..1)
  - `source_span` (session message index range)
  - `ttl_days` (optional, for decaying memories)

### Layer B — Semantic index (vector-ready)

- New folder: `memory/index/`
- Start with local embedding provider abstraction and pluggable backend.
- Backends:
  1) MVP: brute-force cosine search over small local vectors persisted to JSON/NPY.
  2) Production: SQLite backend when configured (`json` remains default/simple mode).
- Retrieval API should support:
  - `query -> top_k memories`
  - hybrid scoring: semantic score + recency + salience + confidence

### Layer C — Canonical profile memory

- Keep `memory/MEMORY.md` for readable long-term memory.
- Also maintain `memory/profile.json` for machine-safe facts:
  - `preferences`, `stable_facts`, `active_projects`, `relationships`, `constraints`.
- `MEMORY.md` can be generated from `profile.json` + selected events.

### Layer D — Reflection + contradiction checks

- During consolidation:
  - detect contradictions with profile facts
  - update confidence instead of blindly overwriting
  - mark stale beliefs with `last_verified_at`

---

## 3) Integration with Existing Nanobot Code

### `nanobot/agent/memory.py`

Refactor `MemoryStore` into three responsibilities:

1. `MemoryStore` (file IO / persistence)
2. `MemoryExtractor` (LLM extraction into typed events)
3. `MemoryRetriever` (hybrid retrieval for prompt context)

`consolidate()` becomes a pipeline:

- gather unconsolidated turns
- extract candidate events
- deduplicate / contradiction check
- persist events/profile/history
- optionally regenerate `MEMORY.md`

### `nanobot/agent/context.py`

Replace "inject whole MEMORY.md only" with retrieval pack assembly:

- `Top stable profile facts` (compact)
- `Top-k episodic memories` relevant to current message
- `Recent unresolved tasks/decisions`

Keep hard token budget (e.g., 600–1200 tokens memory section) to avoid context bloat.

### `nanobot/config/schema.py`

Add config knobs under agent defaults:

- `memory_mode`: `legacy|hybrid`
- `memory_retrieval_k`: int
- `memory_token_budget`: int
- `memory_recency_half_life_days`: float
- `memory_enable_contradiction_check`: bool
- `memory_embedding_provider`: string (optional)

### `nanobot/agent/tools/filesystem.py` + memory skill docs

Add a user-facing memory inspect command pattern (can be skill/tool first):

- show why a memory was retrieved
- allow pin/unpin critical facts
- mark memory as wrong/outdated

---

## 4) ML/IR Strategy

### Scoring function (simple + robust)

For each candidate memory `m`:

`score(m) = w_sem * sim(q,m) + w_rec * recency(m) + w_sal * salience(m) + w_conf * confidence(m)`

with a recency decay:

`recency(m) = exp(-age_days / half_life_days)`

Start with fixed weights and tune from offline eval.

### Deduplication

- First pass: lexical normalization + hash.
- Second pass: semantic near-duplicate threshold (e.g., cosine > 0.92).
- Keep higher confidence/newer memory, merge provenance.

### Contradiction handling

- Candidate contradicts canonical fact -> do not delete immediately.
- Create "conflict set" and update confidence with evidence counts.
- Prefer recent + explicitly confirmed user statements.

---

## 5) Phased Delivery Plan (low risk)

### Phase 1 — Structured events (no embeddings)

- Add `events.jsonl` + typed extraction during consolidation.
- Keep existing `MEMORY.md` + `HISTORY.md` behavior unchanged.
- Add unit tests for extraction format and persistence.

### Phase 2 — Hybrid retrieval

- Add local embedding index and retrieval API.
- Inject top-k memories into context with token budget.
- Add retrieval quality tests with synthetic conversations.

### Phase 3 — Profile + contradiction engine

- Add `profile.json` and conflict tracking.
- Generate concise `MEMORY.md` snapshot from profile.
- Add staleness/verification metadata.

### Phase 4 — Observability + controls

- Metrics and debug logs:
  - memory retrieval hit rate
  - contradiction rate
  - memory token usage
  - user correction rate
- Optional CLI command(s): `nanobot memory inspect|rebuild|verify`

---

## 6) Evaluation: What "better memory" means

Track these KPIs before/after:

1. **Recall@k**: does the right past fact appear in retrieved memories?
2. **Precision@k**: are retrieved memories relevant to the current query?
3. **Contradiction Rate**: conflicting facts surfaced per 100 turns.
4. **Staleness Rate**: recalled memories older than allowed TTL without verification.
5. **Token Efficiency**: memory tokens / prompt tokens ratio.
6. **User Correction Rate**: how often user says "that’s wrong" or updates memory.

---

## 7) Immediate Next Branches

Recommended branch sequence from this branch:

1. `feat/memory-events-jsonl`
2. `feat/memory-hybrid-retrieval`
3. `feat/memory-profile-conflicts`
4. `feat/memory-observability`

This keeps changes reviewable and rollback-safe.
