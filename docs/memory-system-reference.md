# Nanobot Memory System — Complete Reference

> Exhaustive documentation of all 9 persistent data types, their interactions, timing, and data flows.

---

## Architecture Overview

All persistent memory lives in a unified SQLite database (`workspace/memory/memory.db`) with 7 tables: `events`, `events_fts` (FTS5), `events_vec` (sqlite-vec), `profile`, `history`, `snapshots`, `entities`, `edges`. Sessions are stored separately as JSONL files.

**Key principle:** The agent has no direct memory write tool. All memory is extracted automatically by the consolidation pipeline (LLM-based) after conversations grow large enough. The only agent-initiated write is the feedback tool.

---

## 1. Memory Events

**What it stores:** Structured memory items — preferences, facts, tasks, decisions, constraints, relationships. Each has an ID, type, summary, timestamp, source, status, confidence, salience, entities, and triples.

**Storage:** SQLite `events` table, dual-indexed via `events_fts` (FTS5 full-text) and `events_vec` (sqlite-vec cosine embeddings).

**Written by:**
- **Consolidation pipeline** (primary) — LLM extracts events from old conversation messages
- **Heuristic extractor** (fallback) — regex + keyword patterns when LLM extraction fails
- **Feedback tool** — creates feedback events directly in SQLite `events` table
- **Live user corrections** — profile correction pipeline extracts correction events

**Read by:**
- **Memory retriever** — dual search (vector KNN + FTS5) → RRF fusion → scoring → reranking
- **Snapshot builder** — reads recent events for "Open Tasks & Decisions" section
- **Graph augmenter** — reads entity triples from events for graph context

**In LLM context:** Yes — retrieved events appear under "Semantic Memories", "Episodic Memories", and "Reflection" sections. Token budgeted per intent type.

**Required fields:** `type` (preference|fact|task|decision|constraint|relationship), `summary`
**Optional fields:** `timestamp`, `entities`, `salience`, `confidence`, `ttl_days`, `triples`

**Deduplication:** Three levels in `EventIngester.append_events()`:
1. Exact ID match → merge
2. Semantic supersession → mark old as superseded, link new
3. Semantic duplicate → merge with similarity score

---

## 2. Profile (Beliefs)

**What it stores:** 5 sections of user-specific beliefs:
- `preferences` — "User prefers concise responses"
- `stable_facts` — "User works at Company X"
- `active_projects` — "D22648 Finance Strategic Data Transformation"
- `relationships` — "Alice is the project lead"
- `constraints` — "Never run destructive commands without confirmation"

Each entry is a `BeliefRecord` with: id, text, confidence (0.05–0.99), evidence_count, evidence_event_ids, status (active|stale|conflicted|retracted), created_at, last_seen_at, pinned, supersedes/superseded_by links.

**Storage:** SQLite `profile` table (key="profile", value=JSON blob).

**Written by:**
- **Consolidation pipeline** — extracts `profile_updates` from LLM consolidation
- **Live user corrections** — `ProfileStore.apply_live_user_correction()` detects patterns like "correction:", "not true", "I meant"
- **Conflict resolution** — `ConflictManager.resolve_conflict()` when confidence gap ≥ 0.25

**Read by:**
- **Context assembler** — formats profile sections into Markdown for system prompt
- **Snapshot builder** — renders into memory snapshot
- **Retrieval scorer** — profile alignment scoring during retrieval

**In LLM context:** Yes — formatted under section headers (Preferences, Stable Facts, etc.), max 8 items per section.

**Belief lifecycle:**
1. **Created** — confidence 0.65, status "active", evidence_count 1
2. **Updated** — confidence increases with evidence (+0.05 to +0.15 per observation)
3. **Conflicted** — contradicting evidence detected, status → "conflicted"
4. **Retracted** — explicitly overridden, status → "retracted", removed from rendered profile
5. **Stale** — confidence < 0.4 or evidence_count < 2 without recent confirmation
6. **Pinned** — user-pinned beliefs survive stale/retract

---

## 3. Memory Snapshot

**What it stores:** Human-readable Markdown rendering of profile + recent events. This is the agent's "long-term memory" view.

**Structure:**
```markdown
# Memory
## Preferences
- User prefers concise responses (conf=0.75)
## Stable Facts
- User works at Company X (conf=0.80)
## Open Tasks & Decisions
- [2026-03-10] (task) Complete comprehensive project summary
<!-- user-pinned -->
[User annotations preserved across rebuilds]
<!-- end-user-pinned -->
```

**Storage:** SQLite `snapshots` table (key="current").

**Written by:** `MemorySnapshot.rebuild_memory_snapshot(write=True)` — called at the end of every consolidation. Reads profile + events from SQLite, renders Markdown, writes to `snapshots` table.

**Read by:** `ContextAssembler.build()` — reads snapshot from SQLite, truncates to `memory_md_token_cap` (default 1500), includes in system prompt.

**In LLM context:** Yes — appears at the top of the Memory section, capped at 1500 tokens. Query-ranked by keyword overlap with user message.

**User-pinned sections** delimited by `<!-- user-pinned -->` / `<!-- end-user-pinned -->` are preserved across rebuilds.

---

## 4. History

**What it stores:** Timestamped narrative summaries of consolidated conversations. Each entry is 2-5 sentences describing key events, decisions, and topics from a consolidation batch.

**Storage:** SQLite `history` table (id, entry, created_at).

**Written by:** Consolidation pipeline — after LLM extraction, `db.append_history(history_entry)` writes to SQLite.

**Read by:** Rarely — audit trail only. Not currently injected into LLM context. Available via `nanobot memory inspect`.

**In LLM context:** No.

---

## 5. Knowledge Graph

**What it stores:**
- **Entities:** canonical name, type (PERSON, PROJECT, DATABASE, etc.), aliases, properties, first_seen, last_seen
- **Edges:** source → predicate → target with confidence and evidence event_id

**Entity types:** PERSON, SYSTEM, SERVICE, DATABASE, API, CONCEPT, TECHNOLOGY, FRAMEWORK, PATTERN, LOCATION, PROJECT, ORGANIZATION, AGENT, USER, TASK, TOOL, etc.

**Relationship types:** WORKS_ON, WORKS_WITH, USES, LOCATED_IN, CAUSED_BY, RELATED_TO, OWNS, DEPENDS_ON, SUPERSEDES, MENTIONS, CONSTRAINED_BY, PERFORMS, EXECUTES, CALLS, PRODUCES, etc.

**Storage:** SQLite `entities` and `edges` tables.

**Written by:** Event ingestion — `KnowledgeGraph.ingest_event_triples()` extracts entities and relationships from event triples during `EventIngester.append_events()`.

**Read by:**
- **Graph augmenter** — queries entity neighbors (2-hop BFS) to enrich retrieved events
- **Entity resolver** — maps user mentions to canonical entity names via alias map
- **Context assembler** — builds "Entity Graph" section with relationship lines

**In LLM context:** Yes — "Entity Graph" section with formatted triples:
```
- nanobot [tool] → EXECUTES → consolidate_memory [action]
- PostgreSQL [database] → USED_BY → nanobot [tool]
```
Token budgeted (15-19% depending on intent).

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

**Read by:** `feedback_summary(db)` queries `db.read_events(type="feedback")`, unpacks metadata, and aggregates stats for system prompt:
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
```

**Storage:** JSONL files at `workspace/sessions/{safe_key}.jsonl`. First line is metadata, remaining lines are messages.

**Written by:** `MessageProcessor._save_turn()` after every agent turn. Tool results truncated to `tool_result_max_chars` (default 2000) when saved. Session metadata updated on every save.

**Read by:**
- `Session.get_history(max_messages=500)` — returns unconsolidated messages for LLM context
- Aligns to user turns (drops orphaned leading tool results)
- Repairs broken tool_call ↔ tool_result pairings from mid-crash recovery
- Clamps tool_call IDs to 40 chars (OpenAI limit) via deterministic hashing

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
- ONNX MiniLM-L-6-v2: 384D
- HashEmbedder (fallback): 4D (deterministic, no ML)

**Storage:** sqlite-vec virtual table `events_vec` in `memory.db`.

**Written by:** `EventIngester.append_events()` — embeds each event's summary via `Embedder.embed()` (async via `asyncio.to_thread`), stores with event.

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
└─ 5. SAVE TURN
   └─ Session (type 7) → append messages to JSONL
```

### Consolidation Flow (background, periodic)

```
Trigger: unconsolidated messages >= memory_window (50)
│
├─ 1. SELECT old messages (before last_consolidated pointer)
│
├─ 2. LLM EXTRACTION (consolidate_memory tool)
│  ├─ history_entry → History (type 4) via db.append_history()
│  ├─ events → Events (type 1) via EventIngester
│  │  ├─ Embeddings (type 9) generated per event
│  │  └─ Triples → Knowledge Graph (type 5) via ingest_event_triples()
│  └─ profile_updates → Profile (type 2) via ProfileStore
│
├─ 3. REBUILD SNAPSHOT
│  └─ Profile + Events → Snapshot (type 3) via rebuild_memory_snapshot()
│
└─ 4. ADVANCE POINTER
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

### Token Budget Allocation by Intent

| Intent | Profile | Semantic | Episodic | Graph | Long-term | Reflection | Unresolved |
|--------|---------|----------|----------|-------|-----------|------------|------------|
| fact_lookup | 23% | 20% | 5% | 19% | 28% | 0% | 5% |
| debug_history | 10% | 10% | 35% | 15% | 15% | 5% | 10% |
| planning | 15% | 20% | 20% | 15% | 15% | 5% | 10% |
| reflection | 10% | 15% | 10% | 15% | 15% | 25% | 10% |
| constraints | 28% | 24% | 5% | 19% | 19% | 0% | 5% |

Total budget: 900 tokens (default), minimum 40 per section.

---

## Configuration Parameters

| Parameter | Default | Controls |
|-----------|---------|----------|
| `memoryRetrievalK` | 6 | Number of events retrieved per query |
| `memoryTokenBudget` | 900 | Total tokens for memory context |
| `memoryMdTokenCap` | 1500 | Max tokens for memory snapshot |
| `memoryWindow` | 50 | Messages before consolidation triggers |
| `memoryEnableContradictionCheck` | true | Detect belief conflicts during consolidation |
| `memoryConflictAutoResolveGap` | 0.25 | Min confidence gap for auto-resolving conflicts |
| `toolResultMaxChars` | 2000 | Truncation limit for tool results in session |
| `toolResultContextTokens` | 500 | Token budget for tool results in compression |
| `graphEnabled` | false | Enable knowledge graph features |
| `rerankerMode` | "enabled" | Cross-encoder reranking |
| `rerankerAlpha` | 0.5 | Reranker score blending weight |
