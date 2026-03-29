# Nanobot Memory System — Complete Reference

> Exhaustive documentation of all 10 persistent data types, their interactions, timing, and data flows.
> Last verified against codebase: 2026-03-28.

---

## Architecture Overview

All persistent memory lives in a unified SQLite database (`workspace/memory/memory.db`) with 9 tables: `events`, `events_fts` (FTS5), `events_vec` (sqlite-vec), `profile`, `history`, `snapshots`, `entities`, `edges`, `strategies`. Sessions are stored separately as JSONL files. The database uses `PRAGMA journal_mode=WAL` for concurrent read access and `check_same_thread=False` for safe async dispatch via `asyncio.to_thread`.

**Key principle:** The agent has no direct memory write tool. All memory is extracted automatically by the consolidation pipeline (LLM-based) after conversations grow large enough, or by micro-extraction after each turn when enabled. The only agent-initiated write is the feedback tool.

---

## 1. Memory Events

**What it stores:** Structured memory items — preferences, facts, tasks, decisions, constraints, relationships. Each has an ID, type, summary, timestamp, source, status, confidence, salience, entities, triples, and rich metadata.

**Storage:** SQLite `events` table (columns: `id TEXT PRIMARY KEY`, `type TEXT NOT NULL`, `summary TEXT NOT NULL`, `timestamp TEXT NOT NULL`, `source TEXT`, `status TEXT DEFAULT 'active'`, `metadata TEXT` (JSON), `created_at TEXT NOT NULL`), dual-indexed via `events_fts` (FTS5 full-text, synced by triggers) and `events_vec` (sqlite-vec cosine embeddings).

**FTS5 sync:** Three triggers (`events_ai`, `events_ad`, `events_au`) automatically keep `events_fts` synchronized with the `events` table on INSERT, DELETE, and UPDATE.

**Written by:**
- **Consolidation pipeline** (primary) — LLM extracts events from old conversation messages via `consolidate_memory` tool call
- **Micro-extraction** (per-turn) — lightweight LLM extraction after each agent turn (when `micro_extraction_enabled=true`)
- **Heuristic extractor** (fallback) — regex + keyword patterns when LLM extraction fails; max 20 events, 220-char summary cap, fixed salience 0.55
- **Feedback tool** — creates feedback events directly in SQLite `events` table
- **Live user corrections** — profile correction pipeline extracts correction events (salience 0.85, confidence 0.9, TTL 365 days)

**Read by:**
- **Memory retriever** — dual search (vector KNN + FTS5) -> RRF fusion -> scoring -> reranking
- **Snapshot builder** — reads recent events for "Open Tasks & Decisions" and "Recent Episodic Highlights" sections
- **Graph augmenter** — reads entity triples from events for graph context

**In LLM context:** Yes — retrieved events appear under "Relevant Semantic Memories", "Relevant Episodic Memories", and "Relevant Reflection Memories" sections. Token budgeted per intent type.

**Event types:** `preference | fact | task | decision | constraint | relationship` (default `"fact"`)

**Memory types:** `semantic | episodic | reflection` (default `"episodic"`)

**Stability levels:** `high | medium | low` (default `"medium"`)

**MemoryEvent model fields:**
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | str | `""` (auto-generated) | SHA1 of `type|summary|timestamp[:16]`, first 16 hex chars |
| `timestamp` | str | now (UTC ISO-8601) | |
| `type` | EventType | `"fact"` | Unknown types coerced to `"fact"` |
| `summary` | str | **(required)** | Must be non-empty after stripping |
| `memory_type` | MemoryType | `"episodic"` | task/decision -> episodic; preference/fact/constraint/relationship -> semantic |
| `confidence` | float | 0.7 | Clamped [0.0, 1.0] |
| `salience` | float | 0.6 | Clamped [0.0, 1.0] |
| `stability` | Stability | `"medium"` | Inferred from content: semantic+no-incident -> high, episodic+incident -> low |
| `source` | str | `"chat"` | |
| `entities` | list[str] | `[]` | Up to 10 entities per event |
| `triples` | list[KnowledgeTriple] | `[]` | Up to 10 triples per event |
| `ttl_days` | int \| None | `None` | `None` or positive; reflection memories get 30 days if they have evidence_refs |
| `topic` | str | `""` | Auto-classified: preference -> user_preference, fact -> knowledge, task -> task_progress, etc. |
| `status` | str \| None | `None` | Task/decision events get episodic status: `"open"` or `"resolved"` |
| `evidence_refs` | list[str] | `[]` | Reflection memories without evidence_refs are downgraded to episodic |
| `canonical_id` | str | `""` | Supersession tracking |
| `supersedes_event_id` | str | `""` | Links to event this one replaces |
| `metadata` | dict | `{}` | Extra fields packed into `metadata._extra` for round-trip survival |

**Resolved markers:** `"done"`, `"completed"`, `"resolved"`, `"closed"`, `"finished"`, `"cancelled"`, `"canceled"` — used to auto-infer episodic status.

**Deduplication:** Three levels in `EventIngester.append_events()`:
1. **Exact ID match** -> merge
2. **Semantic supersession** -> mark old as superseded, link new (requires negation flip + token overlap >= 0.45 + lexical/semantic similarity >= 0.35)
3. **Semantic duplicate** -> merge with similarity score. Composite: `0.4 * semantic + 0.45 * lexical + 0.15 * entity_overlap`. Duplicate if any of:
   - lexical >= 0.84
   - semantic >= 0.94
   - lexical >= 0.60 AND semantic >= 0.86
   - entity_overlap >= 0.33 AND (lexical >= 0.42 OR semantic >= 0.52)
   - entity_overlap >= 0.30 AND lexical >= 0.25 AND same_type

**Merge behavior:** Entities unioned (deduplicated), confidence averaged + 0.03 boost (clamped [0, 1]), salience takes max, evidence capped at 20 items, source spans merged to cover both, timestamp uses newer.

---

## 2. Profile (Beliefs)

**What it stores:** 5 sections of user-specific beliefs:
- `preferences` — "User prefers concise responses"
- `stable_facts` — "User works at Company X"
- `active_projects` — "D22648 Finance Strategic Data Transformation"
- `relationships` — "Alice is the project lead"
- `constraints` — "Never run destructive commands without confirmation"

Each entry is a `BeliefRecord` with: `id` (deterministic: `"bf-" + SHA1(section|norm_text|created_at)[:8]`), `field` (section name), `text`, `confidence` (0.05-0.99, default 0.65), `evidence_count` (default 1), `evidence_event_ids` (list, max 10 entries), `status` (active|stale|conflicted|retracted, default "active"), `created_at`, `last_seen_at`, `pinned` (bool), `supersedes_id`/`superseded_by_id` links.

**Storage:** SQLite `profile` table (key="profile", value=JSON blob). The JSON structure includes: the 5 section lists (string arrays), `conflicts` array, `last_verified_at` timestamp, `meta` dict (per-section metadata keyed by normalized text), and `updated_at` timestamp.

**Written by:**
- **Consolidation pipeline** — extracts `profile_updates` from LLM consolidation
- **Live user corrections** — `CorrectionOrchestrator.apply_live_user_correction()` with `enable_contradiction_check` flag; detects correction language markers ("corrected", "changed to", "updated to", "actually", "replaced by", "switched to", "migrated to")
- **Conflict resolution** — `ConflictManager` auto-resolves when confidence gap >= `conflict_auto_resolve_gap` (default 0.25)

**Read by:**
- **Context assembler** — formats profile sections into Markdown for system prompt (max 6 items per section, sorted by pinned then confidence descending, stale excluded unless pinned)
- **Snapshot builder** — renders into memory snapshot (max 8 items per section)
- **Retrieval scorer** — profile alignment scoring during retrieval

**In LLM context:** Yes — formatted under section headers (Preferences, Stable Facts, etc.).

**Belief lifecycle:**
1. **Created** — confidence 0.65, status "active", evidence_count 1
2. **Re-observed** — confidence bumped +0.03 (during consolidation); +0.1 for non-conflicted new beliefs
3. **Conflicted** — contradicting evidence detected (negation flip + 0.55 token overlap in `ConflictManager`, or 0.45 overlap in dedup supersession), status -> "conflicted"; old value -0.12, new value -0.2 confidence (min 0.35)
4. **Retracted** — explicitly overridden, status -> "retracted", removed from rendered profile
5. **Stale** — confidence < 0.4 or evidence_count < 2 without recent confirmation; or last_seen_at older than 90 days
6. **Pinned** — user-pinned beliefs survive stale penalties and reactivate from stale
7. **Auto-resolved** — when confidence gap >= 0.25, winner gets +0.08 boost; also resolves by temporal recency or correction language markers

**Confidence bounds:** All updates clamped to [0.05, 0.99].

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

**Storage:** SQLite `snapshots` table (key="current", content TEXT, updated_at TEXT).

**Written by:** `MemorySnapshot.rebuild_memory_snapshot(write=True)` — called at the end of every consolidation. Reads profile + events from SQLite, renders Markdown, writes to `snapshots` table. Profile sections show max 8 items each. Timestamps truncated to 16 chars.

**Read by:** `ContextAssembler.build()` — reads snapshot from SQLite via `db.read_snapshot("current")`, truncates to token budget allocation for `long_term` section (derived from `memory_md_token_cap`, default 1500). Truncation is query-aware: splits by `## ` headings, scores each section by keyword overlap with query + brevity bonus (`0.5 / max(1, section_tokens / 100)`), greedily selects top-scoring sections that fit the budget, preserves original order.

**In LLM context:** Yes — appears as "Long-term Memory (project-specific)" section. When truncated, a note "(some long-term memory sections omitted to fit context budget)" is appended.

**User-pinned sections** delimited by `<!-- user-pinned -->` / `<!-- end-user-pinned -->` are preserved across rebuilds (extracted before rebuild, restored after).

---

## 4. History

**What it stores:** Timestamped narrative summaries of consolidated conversations. Each entry is 2-5 sentences describing key events, decisions, and topics from a consolidation batch.

**Storage:** SQLite `history` table (`id INTEGER PRIMARY KEY AUTOINCREMENT`, `entry TEXT NOT NULL`, `created_at TEXT NOT NULL`). Entries read in ascending creation order.

**Written by:** Consolidation pipeline — after LLM extraction, `db.append_history(history_entry)` writes to SQLite. Falls back to joining the first 3 conversation lines if the LLM doesn't produce a history_entry.

**Read by:** Rarely — audit trail only. Not currently injected into LLM context. Available via `nanobot memory inspect`.

**In LLM context:** No.

---

## 5. Knowledge Graph

**What it stores:**
- **Entities:** canonical name (lowercase, spaces->underscores), type (enum), aliases, properties (JSON including `_display_name`), first_seen, last_seen
- **Edges:** source -> predicate -> target with confidence and evidence event_id

**Entity types (EntityType enum, 27 values):** PERSON, USER, SYSTEM, SERVICE, DATABASE, API, CONCEPT, TECHNOLOGY, FRAMEWORK, PATTERN, LOCATION, REGION, ENVIRONMENT, PROJECT, ORGANIZATION, AGENT, TASK, ACTION, OBSERVATION, MEMORY, SESSION, MESSAGE, DOCUMENT, TOOL, MODEL, UNKNOWN

**Entity type hierarchy:** SERVICE/DATABASE/API -> SYSTEM parent; TECHNOLOGY/FRAMEWORK/PATTERN -> CONCEPT parent; REGION/ENVIRONMENT -> LOCATION parent; USER -> PERSON parent.

**Relationship types (RelationType enum, 22 values):** WORKS_ON, WORKS_WITH, USES, LOCATED_IN, CAUSED_BY, RELATED_TO, OWNS, DEPENDS_ON, SUPERSEDES, MENTIONS, CONSTRAINED_BY, PERFORMS, EXECUTES, CALLS, PRODUCES, OBSERVES, STORES, RECALLS, REFERENCES, DERIVED_FROM, SAME_AS, PART_OF

**Agent-native types:** AGENT, USER, TASK, ACTION, OBSERVATION, MEMORY, SESSION, MESSAGE, DOCUMENT, TOOL, MODEL — designed for tracking agent-operational entities.

**Storage:** SQLite `entities` (`name TEXT PK`, `type TEXT DEFAULT 'unknown'`, `aliases TEXT DEFAULT ''`, `properties TEXT DEFAULT '{}'`, `first_seen TEXT`, `last_seen TEXT`) and `edges` (`source TEXT NOT NULL`, `target TEXT NOT NULL`, `relation TEXT NOT NULL`, `confidence REAL DEFAULT 0.7`, `event_id TEXT DEFAULT ''`, `timestamp TEXT DEFAULT ''`; `PRIMARY KEY (source, relation, target)`) tables. Edge upsert maximizes confidence on conflict.

**Written by:** Event ingestion — `KnowledgeGraph.ingest_event_triples()` processes triples from events:
1. Classifies subject and object types via multi-signal entity classifier (6 signals: regex 0.95, keyword 0.85, phrase 0.85, suffix 0.75, role 0.70, capitalization 0.45)
2. Refines types based on predicate hints (e.g., WORKS_ON subject -> PERSON, LOCATED_IN object -> LOCATION)
3. Validates domain/range constraints from `ontology_rules.py`; demotes confidence by 0.5x if violated
4. Upserts entities (merging aliases and properties) and relationships

**Read by:**
- **Graph augmenter** — queries entity neighbors (2-hop depth via `get_related_entity_names_sync()`) to enrich retrieved events
- **Entity resolver** — maps user mentions to canonical entity names via alias map
- **Context assembler** — builds "Entity Graph" section with relationship lines

**In LLM context:** Yes — "Entity Graph" section with formatted triples:
```
- nanobot [tool] -> EXECUTES -> consolidate_memory [action]
- PostgreSQL [database] -> USED_BY -> nanobot [tool]
```
Token budgeted (15-20% depending on intent).

**Entity resolution:** Built-in alias map (pg->postgresql, k8s->kubernetes, js->javascript, ts->typescript, py->python, mongo->mongodb, gh->github, prod->production, dev->development, etc.) plus runtime aliases registered via `register_alias()`.

**Graph traversal:** BFS via recursive CTE in SQLite, depth clamped 1-5, limit 100 edges. Path finding via iterative BFS, returns up to 5 shortest paths.

**Dual-mode operation:** When `graph_enabled=false`, `KnowledgeGraph()` creates a stub where all methods return empty results. When `graph_enabled=true`, `KnowledgeGraph(db=self.db)` uses the SQLite backend.

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

**Read by:** `feedback_summary(db)` in `nanobot/context/feedback_context.py` queries `db.read_events(type="feedback")` (limit 1000), unpacks metadata, and aggregates stats for system prompt:
```
User feedback: 3 positive, 2 negative (5 total).
Recent corrections/complaints:
  - memory: Assistant forgot my workspace path
Most corrected topics: memory (2x)
```
Shows up to 20 recent negative items with comments.

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

**Storage:** JSONL files at `workspace/sessions/{safe_key}.jsonl`. First line is metadata (`_type="metadata"` with `last_consolidated`, `created_at`, `updated_at`), remaining lines are messages. Legacy migration from `~/.nanobot/sessions/` is supported.

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
- `store_with_summary()` — generates LLM summary (temperature=0.0, max_tokens=500) or heuristic fallback, stores both full output + summary
- `store_only()` — stores full output, no summary generation

**Read by:**
- **Cache hit check** — `cache.has(tool_name, args)` on duplicate calls returns cached summary
- **cache_get_slice tool** — agent can page through cached data: `cache_get_slice(cache_key, start=0, end=25)` returns rows/lines from full output. Handles JSON arrays (Excel sheets, generic objects) and line-based slicing.
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
- ONNX all-MiniLM-L6-v2: 384D (mean pooling, L2 normalized)
- HashEmbedder (fallback): 384D (configurable, deterministic SHA256 chain, no ML)

**Storage:** sqlite-vec virtual table `events_vec` (vec0) in `memory.db`. Columns: `id` (INTEGER PK, rowid of events table), `embedding` (float[{dims}], cosine distance).

**Written by:** `EventIngester.append_events()` — embeds each event's summary via `Embedder.embed()` (async via `asyncio.to_thread` for ONNX), stores with event. Vector cleanup on INSERT OR REPLACE: old vector deleted by rowid before new insert.

**Read by:** `UnifiedMemoryDB.search_vector(query_vec, k)` — returns top-k events by cosine distance. Used in the retrieval pipeline's vector search stage.

**In LLM context:** Indirectly — determines which events are retrieved. The embeddings themselves are never shown to the LLM.

**Graceful degradation:**
- If OpenAI API key missing -> falls back to ONNX LocalEmbedder
- If ONNX model unavailable -> falls back to HashEmbedder (deterministic, low quality)
- If all embedding fails -> FTS5-only retrieval (no vector component)

---

## 10. Procedural Memory (Strategies)

**What it stores:** Learned tool-use strategies extracted from guardrail recoveries. Each strategy captures what didn't work, what worked instead, and why.

**Strategy model:**
```python
@dataclass(slots=True, frozen=True)
class Strategy:
    id: str                    # SHA1 of "domain:task_type:strategy[:100]", first 12 hex chars
    domain: str                # "obsidian", "github", "web", "filesystem"
    task_type: str             # task category
    strategy: str              # the instruction text
    context: str               # why this works
    source: str                # "guardrail_recovery" | "user_correction" | "manual"
    confidence: float          # 0.0-1.0, starts at 0.5
    created_at: datetime
    last_used: datetime
    use_count: int
    success_count: int
```

**Storage:** SQLite `strategies` table (`id TEXT PRIMARY KEY`, `domain TEXT NOT NULL`, `task_type TEXT NOT NULL`, `strategy TEXT NOT NULL`, `context TEXT NOT NULL`, `source TEXT NOT NULL DEFAULT 'guardrail_recovery'`, `confidence REAL NOT NULL DEFAULT 0.5`, `created_at TEXT NOT NULL`, `last_used TEXT NOT NULL`, `use_count INTEGER NOT NULL DEFAULT 0`, `success_count INTEGER NOT NULL DEFAULT 0`). Indexes on `domain` and `task_type`.

**Written by:** `StrategyExtractor.extract_from_turn()` — after a turn completes:
1. Iterates guardrail activations with `strategy_tag`
2. Checks if subsequent tool calls succeeded (later iteration, success=True, not empty output)
3. Calls LLM to summarize the recovery pattern (temperature=0.3, max_tokens=150) or uses fallback: `"Use {success_tool} instead of {failed_tool}"`
4. Infers domain from tool names (obsidian > github > web > filesystem)
5. Saves with confidence=0.5

**Read by:** `ContextBuilder.build_system_prompt()` — retrieves relevant strategies from `StrategyStore` and injects them as "Relevant Strategies" section in the system prompt, ordered by confidence descending.

**In LLM context:** Yes — when `StrategyStore` is wired, strategies appear in the system prompt before declarative memory.

**Confidence dynamics:**
- **Turn succeeded (no guardrail fired):** confidence += 0.1 (max 1.0)
- **Turn failed (guardrail fired again):** confidence -= 0.05 (min 0.0)
- **Pruning:** Strategies below 0.1 confidence are pruned via `StrategyStore.prune()`

**Learning feedback loop:**
```
Session 1: guardrail fires -> recovery succeeds -> strategy saved (conf 0.5)
Session 2: strategy in context -> agent follows it -> no guardrail fires -> conf 0.6
Session 5: strategy conf 0.9 -> agent handles correctly every time
```

---

## Interaction Map: How the 10 Types Connect

### Turn-Time Flow (every message)

```
User message arrives
|
+- 1. CONTEXT ASSEMBLY (reads from 6 sources)
|  +- Snapshot (type 3) -> long-term memory section
|  +- Profile (type 2) -> profile memory section
|  +- Events (type 1) via Retriever -> semantic/episodic sections
|  |  +- Embeddings (type 9) -> vector KNN search
|  +- Knowledge Graph (type 5) -> entity graph section
|  +- Feedback (type 6) -> feedback summary section
|  +- Strategies (type 10) -> procedural memory section
|
+- 2. SESSION HISTORY (type 7)
|  +- Recent messages added to conversation
|
+- 3. LLM CALL
|  +- System prompt + history + tools
|
+- 4. TOOL EXECUTION
|  +- Tool Result Cache (type 8) -> cache hit/miss
|  +- Feedback tool -> writes to SQLite events table (type 6)
|
+- 5. SAVE TURN
|  +- Session (type 7) -> append messages to JSONL
|
+- 6. MICRO-EXTRACTION (if enabled)
|  +- Events (type 1) -> background async extraction from turn
|
+- 7. STRATEGY EXTRACTION (if guardrails fired)
   +- Strategies (type 10) -> extracted from guardrail recoveries
```

### Consolidation Flow (background, periodic)

```
Trigger: unconsolidated messages >= memory window (default 100)
|
+- 1. SELECT old messages (keep last window/2 = 50 messages)
|
+- 2. LLM EXTRACTION (consolidate_memory tool)
|  +- history_entry -> History (type 4) via db.append_history()
|  +- events -> Events (type 1) via EventIngester
|  |  +- Embeddings (type 9) generated per event
|  |  +- Triples -> Knowledge Graph (type 5) via ingest_event_triples()
|  +- profile_updates -> Profile (type 2) via ProfileStore
|
+- 3. AUTO-RESOLVE CONFLICTS (max 10 items)
|
+- 4. REBUILD SNAPSHOT
|  +- Profile + Events -> Snapshot (type 3) via rebuild_memory_snapshot()
|
+- 5. ADVANCE POINTER
   +- Session (type 7) last_consolidated updated
```

### Cross-Type Dependencies

| Source | Feeds Into | How |
|--------|-----------|-----|
| Events (1) | Profile (2) | Consolidation extracts profile beliefs from events |
| Events (1) | Knowledge Graph (5) | Event triples ingested as graph edges |
| Events (1) | Snapshot (3) | Recent events rendered in "Open Tasks" and "Episodic Highlights" sections |
| Events (1) | Embeddings (9) | Each event embedded on ingestion |
| Profile (2) | Snapshot (3) | Profile sections rendered in snapshot |
| Profile (2) | Retrieval scoring | Profile alignment boosts/penalizes retrieved events |
| Feedback (6) | Events (1) | Feedback events stored directly in events table |
| Feedback (6) | Profile (2) | Negative feedback lowers belief confidence |
| Session (7) | Events (1) | Consolidation extracts events from session messages |
| Session (7) | History (4) | Consolidation summarizes into history entries |
| Embeddings (9) | Retrieval | Vector KNN search finds relevant events |
| Knowledge Graph (5) | Retrieval | Graph augmenter enriches retrieved results (+0.15 score boost) |
| Tool Cache (8) | Session (7) | Cached summaries stored in tool result messages |
| Strategies (10) | Context | Injected into system prompt as procedural memory |
| Guardrail activations | Strategies (10) | Recovery patterns extracted as reusable strategies |

### Retrieval Pipeline (detailed)

```
Query arrives
|
+- 1. Infer intent (fact_lookup | debug_history | planning | reflection |
|     constraints_lookup | rollout_status | conflict_review)
|
+- 2. Embed query -> vector
|
+- 3. Dual search (concurrent)
|  +- Vector KNN (sqlite-vec, top-k * candidate_multiplier, max 60)
|  +- FTS5 keyword search (OR prefix matching, per-term quoting)
|
+- 4. RRF fusion (k=60, vector_weight=0.7, fts_weight=0.3)
|
+- 5. Metadata enrichment (promote topic, stability, memory_type from _extra)
|
+- 6. Intent-based filtering
|  +- Routing hints: requires_open, requires_resolved, focus_planning,
|  |   focus_architecture, focus_task_decision
|  +- Intent filters: constraints_lookup -> semantic only;
|  |   debug_history -> episodic or infra topics;
|  |   reflection type filtered out for non-reflection intents
|  +- Reflection safety: no evidence_refs -> filtered out
|
+- 7. Scoring (base_score + adjustments + intent_bonus + graph_boost)
|  +- Profile adjustments:
|  |  +- resolved_keep_new_old: -0.18
|  |  +- resolved_keep_new_new: +0.12
|  |  +- superseded: -0.20 (semantic only)
|  |  +- stale profile: -0.08 (unless pinned)
|  |  +- conflicted profile: -0.05
|  +- Intent bonus:
|  |  +- type_boost: per-intent (up to +/- 0.30)
|  |  +- recency: 0.08 * exp(-ln(2) * age_days / half_life_days)
|  |  +- stability_boost: high +0.03, medium +0.01, low -0.02
|  |  +- reflection_penalty: -0.06 (when recency-weighted)
|  +- Graph entity match boost: +0.15
|
+- 8. Cross-encoder reranking (enabled | shadow | disabled)
|  +- CompositeReranker: lexical(0.30) + entity(0.20) + bm25(0.25) +
|  |   recency(0.15, 30-day half-life) + type_match(0.10)
|  +- OnnxCrossEncoderReranker: ms-marco-MiniLM-L-6-v2 via ONNX Runtime
|  |   (max 512 tokens, sigmoid activation, CPU execution)
|  +- Alpha blending: blended = alpha * reranker + (1-alpha) * heuristic
|
+- 9. Truncate to top_k
```

### Per-Intent Retrieval Policy

| Intent | candidate_multiplier | half_life_days | type_boost (sem/epi/ref) |
|--------|---------------------|----------------|--------------------------|
| fact_lookup | 3 | 120 | +0.18 / -0.05 / -0.12 |
| debug_history | 4 | 21 | -0.04 / +0.22 / -0.10 |
| planning | 3 | 45 | +0.10 / +0.08 / -0.06 |
| reflection | 3 | 60 | +0.03 / -0.03 / +0.20 |
| constraints_lookup | 4 | 180 | +0.24 / -0.10 / -0.14 |
| rollout_status | 2 | 365 | +0.30 / -0.16 / -0.20 |
| conflict_review | 4 | 90 | +0.05 / +0.15 / -0.08 |

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

Total budget: 900 tokens (default). Allocation is two-pass: proportional first, then surplus from under-capacity sections redistributed to over-budget sections. Every section with content and non-zero weight gets at least 40 tokens floor.

### Context Assembly Sections (in order)

1. **Long-term Memory** (project-specific) — from snapshot
2. **Profile Memory** — user-specific facts, preferences, constraints (max 6 items/section)
3. **Relevant Semantic Memories** — retrieved factual knowledge
4. **Entity Graph** — verified entity relationships
5. **Relevant Episodic Memories** — past events and interactions
6. **Relevant Reflection Memories** — only when intent is "reflection"
7. **Recent Unresolved Tasks/Decisions** — max 8 items; only scanned for planning/debug/conflict/reflection/task intents

Safety cap: entire memory context truncated if exceeds `budget * 4` characters.

---

## Micro-Extraction (Per-Turn)

When `micro_extraction_enabled: true`, a lightweight extraction runs after every agent turn:

1. User message + assistant response sent to model (configurable via `micro_extraction_model`, default `gpt-4o-mini`)
2. Model extracts structured events (facts, preferences, decisions, etc.) via `save_events` tool call (simplified schema: type, summary, entities, confidence — no profile_updates), or returns empty array
3. Events ingested via `EventIngester` — dedup, embed, graph all happen automatically
4. Runs as async background task via `asyncio.Task` — zero latency impact on response
5. Temperature: 0.0 (deterministic), max_tokens: 500
6. All exceptions caught and logged as warning — failures never block main pipeline

This ensures short sessions (< consolidation window) persist learned information. Full consolidation remains the authoritative pipeline for profile updates, history, and snapshot rebuilds.

---

## Maintenance Operations

`MemoryMaintenance` provides operational health management:

- **`ensure_health()`** — async health check
- **`reindex_from_structured_memory()`** — full reindex (no-op with UnifiedMemoryDB)
- **`seed_structured_corpus()`** — seed with external profile (JSON) and events (JSONL) files; validates structure, coerces events, inserts into DB
- **`_compact_events_for_reindex()`** — removes superseded events and deduplicates by (summary, type, memory_type, topic) key, keeping newest timestamp per group
- **`_backend_stats_for_eval()`** — collects vector_points_count, db_event_count for EvalRunner

---

## Memory Verification

`MemorySnapshot.verify_memory()` produces a health report:

- **Stale events:** older than `stale_days` (default 90) or past TTL
- **Stale profile items:** `last_seen_at` older than `stale_days`; optionally marks status as "stale" and updates `last_verified_at`
- **Open conflicts:** count of unresolved belief conflicts
- **TTL-tracked events:** count of events with `ttl_days` set
- **Belief quality:** categorized as healthy/weak/contradicted/stale based on `ProfileStore.verify_beliefs()`

---

## Heuristic Extraction Details

When LLM extraction fails, `MemoryExtractor.heuristic_extract_events()` uses pattern matching:

**Type detection by keywords:**
| Type | Keywords |
|------|----------|
| preference | "prefer", "i like", "i dislike", "my preference" |
| constraint | "must", "cannot", "can't", "do not", "never" |
| decision | "decided", "we will", "let's", "plan is" |
| task | "todo", "next step", "please", "need to" |
| relationship | "is my", "works with", "project lead", "manager" |
| fact | (default) |

**Type confidence thresholds:** preference 0.70, constraint 0.65, decision 0.55, task 0.50, relationship 0.60, fact 0.45.

**Entity extraction:** Quoted strings (`"..."` or `'...'`), capitalized multi-word phrases, single capitalized words (filtered against 89-word common words list). Max 10 entities.

**Triple extraction:** 8 regex patterns matching relationship phrases (works on, works with, uses, is in/at/from, caused by, depends on, owns, constrained by). Confidence 0.55 for pattern matches, 0.45 for entity-pair inferred triples.

**Correction detection:** Preference corrections (`"I prefer X not Y"`), fact corrections (`"X is Y not Z"`), user correction markers ("that's wrong", "incorrect", "actually", "correction", "update that", etc.).

---

## Configuration Parameters

All memory parameters live in `MemoryConfig` (`nanobot/config/memory.py`) unless noted otherwise.

### Core Parameters

| Config field | Default | Controls |
|-------------|---------|----------|
| `memory.window` | 100 | Messages before consolidation triggers (keeps last window/2) |
| `memory.retrieval_k` | 6 | Number of events retrieved per query |
| `memory.token_budget` | 900 | Total tokens for memory context |
| `memory.md_token_cap` | 1500 | Max tokens for memory snapshot |
| `memory.uncertainty_threshold` | 0.6 | Uncertainty threshold for retrieval |
| `memory.enable_contradiction_check` | true | Detect belief conflicts during consolidation |
| `memory.conflict_auto_resolve_gap` | 0.25 | Min confidence gap for auto-resolving conflicts |
| `memory.graph_enabled` | false | Enable knowledge graph features |
| `memory.micro_extraction_enabled` | false | Feature gate for per-turn extraction |
| `memory.micro_extraction_model` | null (= gpt-4o-mini) | Model for micro-extraction |
| `memory.raw_turn_ingestion` | true | Enable raw turn ingestion |

### Reranker Settings (nested: `memory.reranker`)

| Config field | Default | Controls |
|-------------|---------|----------|
| `reranker.mode` | "enabled" | Cross-encoder reranking mode (enabled/shadow/disabled) |
| `reranker.alpha` | 0.5 | Reranker score blending weight (0.0-1.0) |
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
| `memory.fallback_allowed_sources` | ["profile", "events", "vector_search"] | Fallback sources |
| `memory.fallback_max_summary_chars` | 280 | Max chars for fallback summaries |

### Rollout Gates

| Config field | Default | Controls |
|-------------|---------|----------|
| `memory.rollout_gate_min_recall_at_k` | 0.55 | Minimum recall@k gate |
| `memory.rollout_gate_min_precision_at_k` | 0.25 | Minimum precision@k gate |
| `memory.rollout_gate_max_avg_context_tokens` | 1400.0 | Max average context tokens |
| `memory.rollout_gate_max_history_fallback_ratio` | 0.05 | Max history fallback ratio |

### Section Weights Override

| Config field | Default | Controls |
|-------------|---------|----------|
| `memory.section_weights` | `{}` (empty) | Per-intent token weight overrides (MemorySectionWeights per intent) |

### Vector Settings (nested: `memory.vector`)

| Config field | Default | Controls |
|-------------|---------|----------|
| `vector.user_id` | "nanobot" | Vector sync user identifier |
| `vector.add_debug` | false | Debug logging for vector operations |
| `vector.verify_write` | true | Verify successful vector writes |
| `vector.force_infer` | false | Force vector inference |

### Tool Result Settings (in `AgentConfig`, not `MemoryConfig`)

| Config field | Default | Controls |
|-------------|---------|----------|
| `tool_result_max_chars` | 2000 | Truncation limit for tool results in session |
| `tool_result_context_tokens` | 500 | Token budget for tool results in compression |

### Consolidation Orchestrator Settings (in `AgentConfig`)

| Config field | Default | Controls |
|-------------|---------|----------|
| `max_concurrent` | 3 | Max concurrent consolidation tasks |
