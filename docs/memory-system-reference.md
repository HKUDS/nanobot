# Nanobot Memory System — Complete Reference

> Exhaustive documentation of all 9 persistent data types, their interactions, timing, and data flows.

---

## Architecture Overview

All persistent memory lives in a unified SQLite database (`workspace/memory/memory.db`) with 8 tables: `events`, `events_fts` (FTS5), `events_vec` (sqlite-vec), `profile`, `history`, `snapshots`, `entities`, `edges`. Sessions are stored separately as JSONL files.

**Key principle:** The agent has no direct memory write tool. All memory is extracted automatically by the consolidation pipeline (LLM-based) after conversations grow large enough. The only agent-initiated write is the feedback tool.

---

## 1. Memory Events

**What it stores:** Structured memory items — preferences, facts, tasks, decisions, constraints, relationships. Each has an ID, type, summary, timestamp, source, status, confidence, salience, entities, and triples.

**Storage:** SQLite `events` table, dual-indexed via `events_fts` (FTS5 full-text) and `events_vec` (sqlite-vec cosine embeddings).

**Written by:**
- **Consolidation pipeline** (primary) — LLM extracts events from old conversation messages
- **Micro-extraction** (per-turn) — lightweight LLM extraction after each agent turn (when enabled)
- **Heuristic extractor** (fallback) — regex + keyword patterns when LLM extraction fails
- **Feedback tool** — creates feedback events directly in SQLite `events` table
- **Live user corrections** — profile correction pipeline extracts correction events

**Read by:**
- **Memory retriever** — dual search (vector KNN + FTS5) → RRF fusion → scoring → reranking
- **Snapshot builder** — reads recent events for "Open Tasks & Decisions" section
- **Graph augmenter** — reads entity triples from events for graph context

**In LLM context:** Yes — retrieved events appear under "Relevant Semantic Memories", "Relevant Episodic Memories", and "Relevant Reflection Memories" sections. Token budgeted per intent type.

**Required fields:** `summary` (the only truly required field; `type` defaults to `"fact"`)
**Optional fields:** `id` (auto-generated), `timestamp` (defaults to now), `type` (preference|fact|task|decision|constraint|relationship, default "fact"), `memory_type` (semantic|episodic|reflection, default "episodic"), `confidence` (default 0.7), `salience` (default 0.6), `stability` (high|medium|low, default "medium"), `source` (default "chat"), `entities`, `ttl_days`, `triples`, `metadata`

**Deduplication:** Three levels in `EventIngester.append_events()`:
1. Exact ID match → merge
2. Semantic supersession → mark old as superseded, link new (requires negation flip + lexical/semantic similarity ≥ 0.35)
3. Semantic duplicate → merge with similarity score (lexical ≥ 0.84 OR semantic ≥ 0.94 OR combined thresholds)

---

## 2. Profile (Beliefs)

**What it stores:** 5 sections of user-specific beliefs:
- `preferences` — "User prefers concise responses"
- `stable_facts` — "User works at Company X"
- `active_projects` — "D22648 Finance Strategic Data Transformation"
- `relationships` — "Alice is the project lead"
- `constraints` — "Never run destructive commands without confirmation"

Each entry is a `BeliefRecord` with: `id`, `field` (section name), `text`, `confidence` (0.05–0.99, default 0.65), `evidence_count` (default 1), `evidence_event_ids` (list, max 10 entries), `status` (active|stale|conflicted|retracted, default "active"), `created_at`, `last_seen_at`, `pinned` (bool), `supersedes_id`/`superseded_by_id` links.

**Storage:** SQLite `profile` table (key="profile", value=JSON blob).

**Written by:**
- **Consolidation pipeline** — extracts `profile_updates` from LLM consolidation
- **Live user corrections** — `ProfileStore.apply_profile_updates()` with `enable_contradiction_check` flag; detects correction language markers ("corrected", "changed to", "updated to", "actually", "replaced by", "switched to", "migrated to")
- **Conflict resolution** — `ConflictManager` auto-resolves when confidence gap ≥ 0.25

**Read by:**
- **Context assembler** — formats profile sections into Markdown for system prompt
- **Snapshot builder** — renders into memory snapshot
- **Retrieval scorer** — profile alignment scoring during retrieval

**In LLM context:** Yes — formatted under section headers (Preferences, Stable Facts, etc.), max 6 items per section. Items sorted by (pinned, confidence) descending; stale items excluded unless pinned.

**Belief lifecycle:**
1. **Created** — confidence 0.65, status "active", evidence_count 1
2. **Updated** — confidence bumped +0.03 per re-observation (non-conflicted: +0.1)
3. **Conflicted** — contradicting evidence detected (negation flip + 0.55 token overlap), status → "conflicted"; old value -0.12, new value -0.2 confidence (min 0.35)
4. **Retracted** — explicitly overridden, status → "retracted", removed from rendered profile
5. **Stale** — confidence < 0.4 or evidence_count < 2 without recent confirmation
6. **Pinned** — user-pinned beliefs survive stale penalties
7. **Auto-resolved** — when confidence gap ≥ 0.25, winner gets +0.08 boost

---

## 3. Memory Snapshot

**What it stores:** Human-readable Markdown rendering of profile + recent events. This is the agent's "long-term memory" view.

**Structure:**
```markdown
# Memory

## Profile Summary
### Preferences
- User prefers concise responses (conf=0.75)
### Stable Facts
- User works at Company X (conf=0.80)

## Open Tasks & Decisions (max 6)
- [2026-03-10] (task) Complete comprehensive project summary

## Recent Episodic Highlights (last 30 events)
- [2026-03-10] (fact) User deployed new version

<!-- user-pinned -->
[User annotations preserved across rebuilds]
<!-- end-user-pinned -->
```

**Storage:** SQLite `snapshots` table (key="current").

**Written by:** `MemorySnapshot.rebuild_memory_snapshot(write=True)` — called at the end of every consolidation. Reads profile + events (up to 30) from SQLite, renders Markdown, writes to `snapshots` table.

**Read by:** `ContextAssembler.build()` — reads snapshot from SQLite via `db.read_snapshot("current")`, truncates to token budget allocation for `long_term` section (derived from `memory_md_token_cap`, default 1500). Truncation is query-aware: sections are scored by keyword overlap with the user message, and top-scoring sections are selected first.

**In LLM context:** Yes — appears as "Long-term Memory (project-specific)" section. When truncated, a note "(some long-term memory sections omitted to fit context budget)" is appended.

**User-pinned sections** delimited by `<!-- user-pinned -->` / `<!-- end-user-pinned -->` are preserved across rebuilds.

---

## 4. History

**What it stores:** Timestamped narrative summaries of consolidated conversations. Each entry is 2-5 sentences describing key events, decisions, and topics from a consolidation batch.

**Storage:** SQLite `history` table (id INTEGER PRIMARY KEY AUTOINCREMENT, entry TEXT, created_at TEXT).

**Written by:** Consolidation pipeline — after LLM extraction, `db.append_history(history_entry)` writes to SQLite.

**Read by:** Rarely — audit trail only. Not currently injected into LLM context. Available via `nanobot memory inspect`.

**In LLM context:** No.

---

## 5. Knowledge Graph

**What it stores:**
- **Entities:** canonical name, type (PERSON, PROJECT, DATABASE, etc.), aliases, properties, first_seen, last_seen
- **Edges:** source → predicate → target with confidence and evidence event_id

**Entity types (enum):** PERSON, USER, SYSTEM, SERVICE, DATABASE, API, CONCEPT, TECHNOLOGY, FRAMEWORK, PATTERN, LOCATION, REGION, ENVIRONMENT, PROJECT, ORGANIZATION, AGENT, TASK, ACTION, OBSERVATION, MEMORY, SESSION, MESSAGE, DOCUMENT, TOOL, MODEL, UNKNOWN

**Relationship types (enum):** WORKS_ON, WORKS_WITH, USES, LOCATED_IN, CAUSED_BY, RELATED_TO, OWNS, DEPENDS_ON, SUPERSEDES, MENTIONS, CONSTRAINED_BY, PERFORMS, EXECUTES, CALLS, PRODUCES, OBSERVES, STORES, RECALLS, REFERENCES, DERIVED_FROM, SAME_AS, PART_OF

**Storage:** SQLite `entities` (name TEXT PK, type, aliases, properties, first_seen, last_seen) and `edges` (source, target, relation, confidence REAL DEFAULT 0.7, event_id, timestamp; PRIMARY KEY (source, relation, target)) tables.

**Written by:** Event ingestion — `KnowledgeGraph.ingest_event_triples()` extracts entities and relationships from event triples during `EventIngester.append_events()`.

**Read by:**
- **Graph augmenter** — queries entity neighbors (2-hop depth via `get_related_entity_names_sync()`) to enrich retrieved events
- **Entity resolver** — maps user mentions to canonical entity names via alias map
- **Context assembler** — builds "Entity Graph" section with relationship lines

**In LLM context:** Yes — "Entity Graph" section with formatted triples:
```
- nanobot [tool] → EXECUTES → consolidate_memory [action]
- PostgreSQL [database] → USED_BY → nanobot [tool]
```
Token budgeted (15–20% depending on intent).

**Entity resolution:** Built-in alias map (pg→postgresql, k8s→kubernetes, js→javascript, etc.) plus runtime aliases from profile data.

---

## 6. Feedback

**What it stores:** User ratings (positive/negative) with optional comment and topic.

**Event format in SQLite `events` table:**
```json
{
  "id": "fb-{uuid12}",
  "type": "feedback",
  "summary": "negative on 'calendar' — wrong date",
  "timestamp": "ISO-8601",
  "metadata": {
    "rating": "positive|negative",
    "comment": "optional correction text",
    "topic": "optional label",
    "channel": "web|telegram|...",
    "chat_id": "...",
    "session_key": "channel:chat_id"
  }
}
```

**Storage:** SQLite `events` table directly. Feedback-specific fields (rating, comment, topic, channel) stored in the `metadata` JSON column.

**Written by:** Agent calls `feedback` tool when user expresses satisfaction or correction. `FeedbackTool.execute()` calls `db.insert_event()` synchronously. The agent is instructed to record feedback in the identity prompt.

**Read by:** `feedback_summary(db)` in `nanobot/context/feedback_context.py` queries `db.read_events(type="feedback")`, unpacks metadata, and aggregates stats for system prompt:
```
User feedback: 3 positive, 2 negative (5 total).
Recent corrections/complaints:
  - memory: Assistant forgot my workspace path
Most corrected topics: memory (2x)
```

**In LLM context:** Yes — "Feedback" section in system prompt showing correction rates and recent complaints. Helps agent self-correct.

---

## 7. Sessions

**What it stores:** Raw conversation messages (user, assistant, tool calls, tool results) with timestamps. Append-only — never modified.

**Structure:**
```python
Session:
  key: str                    # "web:abc-123"
  messages: list[dict]        # [{role, content, timestamp, tool_calls?, tool_call_id?}]
  created_at: datetime
  updated_at: datetime
  last_consolidated: int      # Pointer: messages before this index are consolidated
  metadata: dict
```

**Storage:** JSONL files at `workspace/sessions/{safe_key}.jsonl`. First line is metadata (`_type="metadata"` with `last_consolidated`), remaining lines are messages.

**Written by:** `SessionManager` after every agent turn. Tool results truncated to `tool_result_max_chars` (default 2000) when saved. Session metadata updated on every save.

**Read by:**
- `Session.get_history(max_messages=500)` — returns unconsolidated messages for LLM context
- Aligns to user turns (drops leading non-user messages to avoid orphaned tool results)
- Repairs orphaned tool_calls (strips calls lacking matching tool result)
- Clamps tool_call IDs to 40 chars (OpenAI limit) via deterministic hashing (`"tc_" + sha256[:37]`)

**In LLM context:** Yes — recent conversation history included as message array between system prompt and current user message.

**last_consolidated pointer:**
- Points to the message index where consolidation last processed
- Consolidation reads `messages[last_consolidated:]`, extracts memory, then advances the pointer
- Messages before the pointer are "archived" — they won't be re-processed

---

## 8. Tool Result Cache

**What it stores:** Cached tool outputs with LLM-generated summaries for large results.

**Entry format:**
```python
CacheEntry:
  cache_key: str          # SHA256(tool_name:canonical_args)[:12]
  tool_name: str
  full_output: str        # Complete result
  summary: str            # LLM-generated or heuristic summary
  token_estimate: int     # len(output) // 4
  created_at: float
  truncated: bool
```

**Storage:** In-memory LRU (max 500 entries) + disk `workspace/memory/tool_cache.jsonl` (max 50 entries, entries >200KB stay memory-only).

**Written by:** Tool executor after successful execution of cacheable tools where `len(output) > 3000` chars:
- `store_with_summary()` — generates LLM summary (or heuristic fallback), stores both full output + summary
- `store_only()` — stores full output, no summary generation

**Read by:**
- **Cache hit check** — `cache.has(tool_name, args)` on duplicate calls returns cached summary
- **cache_get_slice tool** — agent can page through cached data: `cache_get_slice(cache_key, start=0, end=25)` returns rows/lines from full output
- **to_llm_string()** — if result has `cache_key` in metadata, returns summary instead of full output

**In LLM context:** Summary appears in tool result messages. Agent sees `[tool_name] returned N chars. Preview: ...` and can call `cache_get_slice` for specific ranges.

**Heuristic summary format:**
```
[read_file] returned 11,919 chars of output.
Preview:
{first 400 chars}
...
Full result cached as 4056d3c2e3fc (11,919 chars).
Use cache_get_slice(cache_key="4056d3c2e3fc", start=0, end=25) for raw lines.
```

**Key property:** Tools with `cacheable = False` (like `load_skill`) bypass the cache entirely.

---

## 9. Embeddings / Vector Store

**What it stores:** Dense float32 vectors for every memory event. Dimensionality depends on embedder:
- OpenAI text-embedding-3-small: 1536D
- ONNX all-MiniLM-L6-v2: 384D
- HashEmbedder (fallback): 384D (configurable, deterministic, no ML)

**Storage:** sqlite-vec virtual table `events_vec` (vec0) in `memory.db`. Columns: `id` (INTEGER PK, rowid of events table), `embedding` (float[{dims}], cosine distance).

**Written by:** `EventIngester.append_events()` — embeds each event's summary via `Embedder.embed()` (async via `asyncio.to_thread` for ONNX), stores with event.

**Read by:** `UnifiedMemoryDB.search_vector(query_vec, k)` — returns top-k events by cosine distance. Used in the retrieval pipeline's vector search stage.

**In LLM context:** Indirectly — determines which events are retrieved. The embeddings themselves are never shown to the LLM.

**Graceful degradation:**
- If OpenAI API key missing → falls back to ONNX LocalEmbedder
- If ONNX model unavailable → falls back to HashEmbedder (deterministic, low quality)
- If all embedding fails → FTS5-only retrieval (no vector component)

---

## Interaction Map: How the 9 Types Connect

### Turn-Time Flow (every message)

```
User message arrives
│
├─ 1. CONTEXT ASSEMBLY (reads from 5 sources)
│  ├─ Snapshot (type 3) → long-term memory section
│  ├─ Profile (type 2) → profile memory section
│  ├─ Events (type 1) via Retriever → semantic/episodic sections
│  │  └─ Embeddings (type 9) → vector KNN search
│  ├─ Knowledge Graph (type 5) → entity graph section
│  └─ Feedback (type 6) → feedback summary section
│
├─ 2. SESSION HISTORY (type 7)
│  └─ Recent messages added to conversation
│
├─ 3. LLM CALL
│  └─ System prompt + history + tools
│
├─ 4. TOOL EXECUTION
│  ├─ Tool Result Cache (type 8) → cache hit/miss
│  └─ Feedback tool → writes to SQLite events table (type 6)
│
├─ 5. SAVE TURN
│  └─ Session (type 7) → append messages to JSONL
│
└─ 6. MICRO-EXTRACTION (if enabled)
   └─ Events (type 1) → background async extraction from turn
```

### Consolidation Flow (background, periodic)

```
Trigger: unconsolidated messages >= memory window (default 100)
│
├─ 1. SELECT old messages (keep last window/2 = 50 messages)
│
├─ 2. LLM EXTRACTION (consolidate_memory tool)
│  ├─ history_entry → History (type 4) via db.append_history()
│  ├─ events → Events (type 1) via EventIngester
│  │  ├─ Embeddings (type 9) generated per event
│  │  └─ Triples → Knowledge Graph (type 5) via ingest_event_triples()
│  └─ profile_updates → Profile (type 2) via ProfileStore
│
├─ 3. AUTO-RESOLVE CONFLICTS (max 10 items)
│
├─ 4. REBUILD SNAPSHOT
│  └─ Profile + Events → Snapshot (type 3) via rebuild_memory_snapshot()
│
└─ 5. ADVANCE POINTER
   └─ Session (type 7) last_consolidated updated
```

### Cross-Type Dependencies

| Source | Feeds Into | How |
|--------|-----------|-----|
| Events (1) | Profile (2) | Consolidation extracts profile beliefs from events |
| Events (1) | Knowledge Graph (5) | Event triples ingested as graph edges |
| Events (1) | Snapshot (3) | Recent events rendered in "Open Tasks" section |
| Events (1) | Embeddings (9) | Each event embedded on ingestion |
| Profile (2) | Snapshot (3) | Profile sections rendered in snapshot |
| Profile (2) | Retrieval scoring | Profile alignment boosts/penalizes retrieved events |
| Feedback (6) | Events (1) | Feedback events stored directly in events table |
| Feedback (6) | Profile (2) | Negative feedback lowers belief confidence |
| Session (7) | Events (1) | Consolidation extracts events from session messages |
| Session (7) | History (4) | Consolidation summarizes into history entries |
| Embeddings (9) | Retrieval | Vector KNN search finds relevant events |
| Knowledge Graph (5) | Retrieval | Graph augmenter enriches retrieved results |
| Tool Cache (8) | Session (7) | Cached summaries stored in tool result messages |

### Retrieval Pipeline (detailed)

```
Query arrives
│
├─ 1. Infer intent (fact_lookup | debug_history | planning | reflection |
│     constraints_lookup | rollout_status | conflict_review)
│
├─ 2. Embed query → vector
│
├─ 3. Dual search
│  ├─ Vector KNN (sqlite-vec, top-k * candidate_multiplier)
│  └─ FTS5 keyword search (prefix matching, per-term quoting)
│
├─ 4. RRF fusion (k=60, vector_weight=0.7)
│
├─ 5. Metadata enrichment (topic, stability, memory_type)
│
├─ 6. Intent-based filtering
│
├─ 7. Scoring (base_score + profile_adjustments + intent_bonus + graph_boost)
│  ├─ Profile adjustments: superseded -0.2, stale -0.08, conflicted -0.05
│  ├─ Stability boost: high +0.03, medium +0.01, low -0.02
│  ├─ Recency decay: exp(-ln(2) * age_days / half_life_days)
│  ├─ Reflection penalty: -0.06 (when recency-weighted)
│  └─ Graph entity match boost: +0.15
│
├─ 8. Cross-encoder reranking (enabled | shadow | disabled)
│  ├─ CompositeReranker: lexical(0.30) + entity(0.20) + bm25(0.25) +
│  │   recency(0.15) + type_match(0.10)
│  └─ OnnxCrossEncoderReranker: ms-marco-MiniLM-L-6-v2 via ONNX
│  └─ Alpha blending: blended = alpha * reranker + (1-alpha) * heuristic
│
└─ 9. Truncate to top_k
```

### Token Budget Allocation by Intent

| Intent | Long-term | Profile | Semantic | Episodic | Reflection | Graph | Unresolved |
|--------|-----------|---------|----------|----------|------------|-------|------------|
| fact_lookup | 28% | 23% | 20% | 5% | 0% | 19% | 5% |
| debug_history | 15% | 10% | 10% | 35% | 5% | 15% | 10% |
| planning | 15% | 15% | 20% | 20% | 5% | 15% | 10% |
| reflection | 15% | 10% | 15% | 10% | 25% | 15% | 10% |
| constraints_lookup | 19% | 28% | 24% | 5% | 0% | 19% | 5% |
| rollout_status | 25% | 15% | 30% | 0% | 0% | 20% | 10% |
| conflict_review | 15% | 20% | 20% | 15% | 0% | 20% | 10% |

Total budget: 900 tokens (default). Sections are allocated proportionally with a two-pass algorithm; surplus from sections that fit entirely is redistributed to sections that need more.

### Context Assembly Sections (in order)

1. **Long-term Memory** (project-specific) — from snapshot
2. **Profile Memory** — user-specific facts, preferences, constraints
3. **Relevant Semantic Memories** — retrieved factual knowledge
4. **Entity Graph** — verified entity relationships
5. **Relevant Episodic Memories** — past events and interactions
6. **Relevant Reflection Memories** — only when intent is "reflection"
7. **Recent Unresolved Tasks/Decisions** — max 8 items

Safety cap: entire memory context truncated if exceeds `budget * 4` characters.

---

## Micro-Extraction (Per-Turn)

When `micro_extraction_enabled: true`, a lightweight extraction runs after every agent turn:

1. User message + assistant response sent to `gpt-4o-mini` (configurable via `micro_extraction_model`)
2. Model extracts structured events (facts, preferences, decisions, etc.) via `save_events` tool call, or returns empty array
3. Events ingested via `EventIngester` — dedup, embed, graph all happen automatically
4. Runs as async background task — zero latency impact on response

This ensures short sessions (< consolidation window) persist learned information. Full consolidation
remains the authoritative pipeline for profile updates, history, and snapshot rebuilds.

---

## Configuration Parameters

All memory parameters live in `MemoryConfig` (`nanobot/config/memory.py`) unless noted otherwise.

### Core Parameters

| Config field | Default | Controls |
|-------------|---------|----------|
| `memory.retrieval_k` | 6 | Number of events retrieved per query |
| `memory.token_budget` | 900 | Total tokens for memory context |
| `memory.md_token_cap` | 1500 | Max tokens for memory snapshot |
| `memory.window` | 100 | Messages before consolidation triggers (keeps last window/2) |
| `memory.enable_contradiction_check` | true | Detect belief conflicts during consolidation |
| `memory.conflict_auto_resolve_gap` | 0.25 | Min confidence gap for auto-resolving conflicts |
| `memory.uncertainty_threshold` | 0.6 | Uncertainty threshold for retrieval |
| `memory.graph_enabled` | false | Enable knowledge graph features |
| `memory.micro_extraction_enabled` | false | Feature gate for per-turn extraction |
| `memory.micro_extraction_model` | null (= gpt-4o-mini) | Model for micro-extraction |
| `memory.raw_turn_ingestion` | true | Enable raw turn ingestion |

### Reranker Settings (nested: `memory.reranker`)

| Config field | Default | Controls |
|-------------|---------|----------|
| `reranker.mode` | "enabled" | Cross-encoder reranking mode (enabled/shadow/disabled) |
| `reranker.alpha` | 0.5 | Reranker score blending weight (0.0–1.0) |
| `reranker.model` | "onnx:ms-marco-MiniLM-L-6-v2" | Reranker model identifier |

### Rollout Feature Flags

| Config field | Default | Controls |
|-------------|---------|----------|
| `memory.rollout_mode` | "enabled" | Rollout mode (enabled/shadow/disabled) |
| `memory.type_separation_enabled` | true | Separate memory types in retrieval scoring |
| `memory.router_enabled` | true | Enable retrieval intent routing |
| `memory.reflection_enabled` | true | Enable reflection memories |
| `memory.shadow_mode` | false | Shadow mode for A/B testing |
| `memory.shadow_sample_rate` | 0.2 | Sample rate for shadow comparisons |
| `memory.vector_health_enabled` | true | Vector health monitoring |
| `memory.auto_reindex_on_empty_vector` | true | Auto-reindex when vector table empty |
| `memory.history_fallback_enabled` | false | Enable history fallback search |

### Rollout Gates

| Config field | Default | Controls |
|-------------|---------|----------|
| `memory.rollout_gate_min_recall_at_k` | 0.55 | Minimum recall@k gate |
| `memory.rollout_gate_min_precision_at_k` | 0.25 | Minimum precision@k gate |
| `memory.rollout_gate_max_avg_context_tokens` | 1400.0 | Max average context tokens |
| `memory.rollout_gate_max_history_fallback_ratio` | 0.05 | Max history fallback ratio |

### Tool Result Settings (in `AgentConfig`, not `MemoryConfig`)

| Config field | Default | Controls |
|-------------|---------|----------|
| `tool_result_max_chars` | 2000 | Truncation limit for tool results in session |
| `tool_result_context_tokens` | 500 | Token budget for tool results in compression |
