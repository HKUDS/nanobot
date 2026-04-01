# Nanobot Memory Architecture

> Living document. Governs the memory subsystem design, patterns, and constraints.
> Companion to `cognitive-architecture.md` (agent core) and `architecture.md` (system-wide).
> Last updated: 2026-04-01.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Governing Design Patterns](#governing-design-patterns)
3. [Storage Layer](#storage-layer)
4. [Write Pipeline](#write-pipeline)
5. [Read Pipeline](#read-pipeline)
6. [Knowledge Graph](#knowledge-graph)
7. [Profile and Belief System](#profile-and-belief-system)
8. [Procedural Memory (Strategies)](#procedural-memory)
9. [Composition and Wiring](#composition-and-wiring)
10. [Integration with Agent Core](#integration-with-agent-core)
11. [Extension Points](#extension-points)
12. [Known Technical Debt](#known-technical-debt)
13. [Testing Strategy](#testing-strategy)

---

<a id="architecture-overview"></a>
## 1. Architecture Overview

The memory subsystem is a bounded context within the nanobot modular monolith. It owns
all persistent knowledge: events, profile beliefs, knowledge graph, procedural strategies,
snapshots, and history. The rest of the system interacts with it only through the
`MemoryStore` facade and the `StrategyAccess` CRUD interface.

```
┌─────────────────────────────────────────────────────────────┐
│                      MemoryStore (facade)                    │
│                    nanobot/memory/store.py                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  WRITE PATH  │  │  READ PATH   │  │   PERSISTENCE     │  │
│  │              │  │              │  │                   │  │
│  │ Extractor    │  │ Planner      │  │ ProfileStore      │  │
│  │ MicroExtract │  │ Retriever    │  │ Snapshot          │  │
│  │ Ingester     │  │ Scorer       │  │ CorrectionOrch.   │  │
│  │ Coercer      │  │ Reranker     │  │ ConflictManager   │  │
│  │ Dedup        │  │ GraphAug     │  │                   │  │
│  │ Classifier   │  │ Assembler    │  │                   │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         │                 │                    │              │
│  ┌──────▼─────────────────▼────────────────────▼──────────┐  │
│  │              STORAGE LAYER (shared SQLite)              │  │
│  │  MemoryDatabase -> EventStore, GraphStore               │  │
│  │  9 tables: events, events_fts, events_vec, profile,     │  │
│  │            history, snapshots, entities, edges,          │  │
│  │            strategies                                    │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  GRAPH       │  │  RANKING     │  │   EMBEDDER        │  │
│  │              │  │              │  │                   │  │
│  │ KnowledgeGr. │  │ Composite    │  │ OpenAI (1536D)    │  │
│  │ Classifier   │  │ OnnxCE       │  │ Local (384D)      │  │
│  │ Linker       │  │ Protocol     │  │ Hash (384D)       │  │
│  │ Ontology     │  │              │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Package Map

| Package | Concern | Key Classes |
|---------|---------|-------------|
| `memory/` | Facade, data models, consolidation | `MemoryStore`, `MemoryEvent`, `ConsolidationPipeline`, `Strategy`, `StrategyAccess`, `StrategyExtractor` |
| `memory/db/` | SQLite storage (connection, events, graph) | `MemoryDatabase`, `EventStore`, `GraphStore` |
| `memory/write/` | Ingestion pipeline | `MemoryExtractor`, `MicroExtractor`, `EventIngester`, `EventCoercer`, `EventDeduplicator`, `EventClassifier`, `ConflictManager` |
| `memory/read/` | Retrieval pipeline | `MemoryRetriever`, `RetrievalPlanner`, `RetrievalScorer`, `ContextAssembler`, `GraphAugmenter` |
| `memory/ranking/` | Reranking | `Reranker` (protocol), `CompositeReranker`, `OnnxCrossEncoderReranker` |
| `memory/graph/` | Knowledge graph + ontology | `KnowledgeGraph`, `EntityType`, `RelationType`, `Entity`, `Relationship`, `Triple` |
| `memory/persistence/` | Profile, snapshot, corrections | `ProfileStore`, `MemorySnapshot`, `CorrectionOrchestrator`, `ConflictRecord` |
| `memory/embedder.py` | Embedding protocol + implementations | `Embedder`, `OpenAIEmbedder`, `LocalEmbedder`, `HashEmbedder` |

---

<a id="governing-design-patterns"></a>
## 2. Governing Design Patterns

These patterns keep the memory subsystem stable. Every future change must satisfy them.

### Pattern 1: Single SQLite Database, Shared Connection

All persistent state lives in one `memory.db` file with one `sqlite3.Connection` shared
across all subsystems. WAL mode enables concurrent reads. No external databases, no
separate vector stores, no file-based indexes.

**Rationale:** A single database means a single backup, a single migration path, and
atomic cross-table operations. The previous design had separate Qdrant/ChromaDB vector
stores that added operational complexity without proportional benefit.

**Enforcement:** `MemoryDatabase` is constructed once in `MemoryStore.__init__` and
shared via property access (`db.connection`, `db.event_store`, `db.graph_store`).

### Pattern 2: Fixed-Column Schema with Overflow

The `events` table has only 8 columns. All additional MemoryEvent fields (20+ fields)
are packed into `metadata._extra` JSON on write and unpacked on read. This avoids
schema migrations when new event fields are added.

**Rationale:** New memory event fields are added frequently as the extraction pipeline
evolves. ALTER TABLE on SQLite is expensive for large tables. The overflow pattern
means new fields require zero schema changes.

**Enforcement:** `EventIngester.append_events()` packs extra fields into `metadata._extra`.
`EventIngester.read_events()` unpacks them back. The `events` table DDL never changes.

**Trade-off:** Fields in `_extra` cannot be indexed or queried via SQL. Only `summary`
(via FTS5), `type`, `status`, and `timestamp` are directly queryable.

### Pattern 3: Dual-Source Retrieval with RRF Fusion

Every query hits both vector search (sqlite-vec KNN) and full-text search (FTS5)
concurrently, then fuses results via Reciprocal Rank Fusion. This ensures retrieval
works even when one source degrades (e.g., HashEmbedder produces meaningless vectors).

**Rationale:** Pure vector search fails when embeddings are low quality (HashEmbedder
fallback). Pure FTS fails on semantic similarity. RRF fusion with asymmetric weights
(0.7 vector, 0.3 FTS) captures both signals.

**Enforcement:** `MemoryRetriever._retrieve_unified()` always runs both searches via
`asyncio.gather`. If both return empty, falls back to recency-ordered scan.

### Pattern 4: Intent-Driven Retrieval

Every query is classified into one of 7 intents (fact_lookup, debug_history, planning,
reflection, constraints_lookup, rollout_status, conflict_review). Each intent has its
own policy: candidate multiplier, recency half-life, type boosts, and filtering rules.

**Rationale:** A query about "what failed yesterday" needs different retrieval behavior
than "what are the user's preferences." Intent classification ensures the right events
surface for the right questions.

**Enforcement:** `RetrievalPlanner.plan()` classifies intent via keyword matching.
The resulting `RetrievalPlan` drives filtering, scoring, and budget allocation
downstream.

### Pattern 5: Write Path Convergence

Both write entry points (full consolidation and micro-extraction) converge on
`EventIngester.append_events()` as the single ingestion gate. All dedup, merge, and
persistence logic lives in one place.

**Rationale:** Duplicate logic in parallel write paths is the #1 source of data
inconsistency bugs. A single gate ensures every event gets the same treatment
regardless of origin.

**Enforcement:** `MicroExtractor.submit()` and `ConsolidationPipeline._consolidate_single_tool()`
both call `ingester.append_events()`. No other code path writes events.

### Pattern 6: Facade Hides Internal Complexity

External code (agent, context, tools) interacts only with `MemoryStore` and
`StrategyAccess`. Internal classes (EventIngester, RetrievalScorer, ProfileStore)
are never imported outside the memory package.

**Rationale:** The memory subsystem has 30+ internal classes across 8 subpackages.
Exposing this complexity would create import spaghetti and make refactoring impossible.

**Enforcement:** `memory/__init__.py` exports only 7 symbols: `MemoryDatabase`,
`Embedder`, `HashEmbedder`, `LocalEmbedder`, `OpenAIEmbedder`, `MemoryEvent`,
`MemoryStore`. Import rules in `scripts/check_imports.py` block external packages
from importing `memory.write`, `memory.read`, etc.

---

<a id="storage-layer"></a>
## 3. Storage Layer

### SQLite Schema

```sql
-- Core event storage
CREATE TABLE events (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, summary TEXT NOT NULL,
    timestamp TEXT NOT NULL, source TEXT, status TEXT DEFAULT 'active',
    metadata TEXT, created_at TEXT NOT NULL
);

-- Full-text search (content-synced via triggers)
CREATE VIRTUAL TABLE events_fts USING fts5(
    summary, content=events, content_rowid=rowid
);

-- Vector search (cosine distance, dims frozen at construction)
CREATE VIRTUAL TABLE events_vec USING vec0(
    id INTEGER PRIMARY KEY, embedding float[{dims}] distance_metric=cosine
);

-- User profile beliefs (key-value JSON)
CREATE TABLE profile (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Conversation history summaries
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL, created_at TEXT NOT NULL
);

-- Memory snapshots (MEMORY.md)
CREATE TABLE snapshots (
    key TEXT PRIMARY KEY, content TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- Knowledge graph nodes
CREATE TABLE entities (
    name TEXT PRIMARY KEY, type TEXT DEFAULT 'unknown',
    aliases TEXT DEFAULT '', properties TEXT DEFAULT '{}',
    first_seen TEXT DEFAULT '', last_seen TEXT DEFAULT ''
);

-- Knowledge graph edges
CREATE TABLE edges (
    source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL,
    confidence REAL DEFAULT 0.7, event_id TEXT DEFAULT '',
    timestamp TEXT DEFAULT '',
    PRIMARY KEY (source, relation, target)
);

-- Procedural memory
CREATE TABLE strategies (
    id TEXT PRIMARY KEY, domain TEXT NOT NULL, task_type TEXT NOT NULL,
    strategy TEXT NOT NULL, context TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'guardrail_recovery',
    confidence REAL NOT NULL DEFAULT 0.5, created_at TEXT NOT NULL,
    last_used TEXT NOT NULL, use_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_strategies_domain ON strategies(domain);
CREATE INDEX idx_strategies_task_type ON strategies(task_type);

-- Performance indexes (added PR#122)
CREATE INDEX idx_events_type ON events(type);
CREATE INDEX idx_events_status ON events(status);
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX idx_edges_target ON edges(target);
```

### Key Schema Decisions

**events_vec.id is INTEGER (rowid), not TEXT (events.id):** The join between vector
results and events is `ON e.rowid = v.id`. `INSERT OR REPLACE` changes the rowid, so
`EventStore.insert_event()` explicitly deletes the old vector entry before re-inserting.
Any direct SQL manipulation of `events` outside `EventStore` risks orphaned vectors.

**Edge upsert maximizes confidence:** `ON CONFLICT DO UPDATE SET confidence = MAX(excluded.confidence, confidence)`.
Edges only increase in confidence, never decrease. This is intentional — edge confidence
represents cumulative evidence, not a decaying signal.

**Entity upsert preserves first_seen:** On conflict, `first_seen` is NOT updated. Only
`last_seen`, `type`, `aliases`, `properties` are overwritten.

**Indexes (added in PR#122):** `idx_events_type` on `events(type)`,
`idx_events_status` on `events(status)`, `idx_events_timestamp` on
`events(timestamp DESC)`, and `idx_edges_target` on `edges(target)`. These
support filtered queries in `EventStore.read_events()` and the FTS5 pre-filter
dedup path in `EventIngester._find_dedup_candidates()`.

### Embedder Protocol and Implementations

```python
@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dims(self) -> int: ...
    @property
    def available(self) -> bool: ...
```

| Implementation | Model | Dims | Notes |
|----------------|-------|------|-------|
| `OpenAIEmbedder` | text-embedding-3-small | 1536 | Default, requires `OPENAI_API_KEY` |
| `LocalEmbedder` | all-MiniLM-L6-v2 | 384 | ONNX Runtime, mean pooling, 128-token max, thread-safe lazy init |
| `HashEmbedder` | SHA-256 chain | 384 | Deterministic, no ML, unit-normalized, always available |

Selection cascades through fallbacks: OpenAI -> Hash (default), Local -> Hash (when
`embedding_provider="local"`). `HashEmbedder` produces structurally valid but
semantically meaningless vectors — vector search returns arbitrary results, making
FTS5 the only meaningful retrieval signal.

---

<a id="write-pipeline"></a>
## 4. Write Pipeline

### Two Entry Points, One Gate

```
FULL CONSOLIDATION                    MICRO-EXTRACTION
(background, periodic)                (per-turn, async)
         |                                    |
   ConsolidationPipeline              MicroExtractor.submit()
         |                                    |
   LLM: consolidate_memory           LLM: save_events (simplified)
         |                                    |
   MemoryExtractor.extract_           MemoryEvent.from_dict()
     structured_memory()               (bypasses EventCoercer)
         |                                    |
   EventCoercer.coerce_event()                |
         |                                    |
         +------- CONVERGENCE POINT ----------+
         |
   EventIngester.append_events()
         |
   ┌─────┴──────────────────────────┐
   │  Per candidate (targeted SQL):  │
   │  1. ensure_event_provenance()  │
   │  2. Exact ID: get_event_by_id  │  <- O(1) PK lookup
   │     -> merge if found          │
   │  3. Supersession: FTS5 pre-    │  <- ~30 candidates
   │     filter + negation check    │
   │  4. Duplicate: FTS5 pre-filter │  <- ~30 candidates
   │     + Jaccard -> merge         │
   │  5. New event -> _write_events │  <- embedding=None always
   └────────────────────────────────┘
         |
   (consolidation only)
         |
   ┌─────┴──────────────────────────┐
   │  _ingest_graph_triples()       │  <- micro path skips this
   │  _apply_profile_updates()      │  <- micro path skips this
   │  auto_resolve_conflicts()      │  <- micro path skips this
   │  rebuild_memory_snapshot()     │  <- micro path skips this
   └────────────────────────────────┘
```

### Event Coercion (`EventCoercer`)

Full normalization pipeline for raw LLM output -> `MemoryEvent`:

1. Validate `summary` is non-empty string
2. Coerce `type` to valid `EventType` (default `"fact"`)
3. Coerce/generate `timestamp` (UTC ISO-8601)
4. Clamp `salience` and `confidence` to [0, 1]
5. Coerce `entities` via `_to_str_list`
6. Validate `ttl_days` (positive or None)
7. Infer `episodic_status` for task/decision events
8. Run `EventClassifier.normalize_memory_metadata()` for memory_type, stability, topic
9. Parse triples (subject + object required; predicate defaults to `"RELATED_TO"`)
10. Build or reuse event ID: `SHA1(type|summary|timestamp[:16])[:16]`

### Event Classification (`EventClassifier`)

Determines `memory_type`, `stability`, and `topic` from event content:

| Event Type | Memory Type | Stability | Topic |
|------------|-------------|-----------|-------|
| preference | semantic | high (no incident) / medium (incident) | user_preference |
| fact | semantic | high / medium | knowledge |
| constraint | semantic | high / medium | constraint |
| relationship | semantic | high / medium | social |
| task | episodic | medium / low (incident) | task_progress |
| decision | episodic | medium / low | decision |

**Reflection safety:** Reflections without `evidence_refs` are downgraded to episodic
with `stability="low"` and flagged with `reflection_safety_downgraded=True`.

### Deduplication (`EventDeduplicator`)

Three-level dedup in `append_events()`, evaluated in order:

1. **Exact ID match:** Merge via `merge_events()`
2. **Semantic supersession:** Detects negation conflicts (token containing `" not "` or
   `"n't"` + >= 0.45 token overlap + lexical/semantic >= 0.35). Old event marked
   `"superseded"`, new event links via `supersedes_event_id`.
3. **Semantic duplicate:** Composite score `0.85 * lexical + 0.15 * entity_overlap`
   (note: `semantic = lexical` — embedding similarity not yet implemented). Multi-threshold
   OR condition triggers merge.

**Merge behavior:** Entities unioned, confidence averaged + 0.03 boost, salience takes
max, evidence capped at 20, source spans merged, timestamp uses newer,
`merged_event_count` incremented.

### Micro-Extraction Differences

Micro-extraction bypasses several steps the full path performs:

| Step | Full Consolidation | Micro-Extraction |
|------|-------------------|-----------------|
| LLM schema | Full `_SAVE_EVENTS_TOOL` | Simplified `_MICRO_EXTRACT_TOOL` (no triples, salience, confidence, ttl_days) |
| Event construction | `EventCoercer.coerce_event()` | `MemoryEvent.from_dict()` directly |
| ID generation | `build_event_id()` | Relies on `from_dict` defaults |
| Graph triples | Ingested via `_ingest_graph_triples()` | Skipped entirely |
| Profile updates | Applied via `_apply_profile_updates()` | Skipped entirely |
| Snapshot rebuild | Called at end | Skipped entirely |

---

<a id="read-pipeline"></a>
## 5. Read Pipeline

### Pipeline Stages

```
Query text
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1: PLAN                                       │
│  RetrievalPlanner.plan(query)                        │
│  -> intent (7 types), policy, routing_hints          │
│  Keyword matching, priority-ordered                  │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 2: EMBED                                      │
│  embedder.embed(query) -> float[dims]                │
│  Single async call                                   │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 3: DUAL SEARCH (concurrent)                   │
│  asyncio.gather(                                     │
│    to_thread(search_vector, query_vec, candidate_k), │
│    to_thread(search_fts, query, candidate_k),        │
│  )                                                   │
│  candidate_k = top_k * multiplier, capped at 60      │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 4: RRF FUSION                                 │
│  score(doc) = Σ weight_i / (60 + rank_i)            │
│  vector_weight=0.7, fts_weight=0.3                   │
│  Stored in item["_rrf_score"]                        │
│                                                      │
│  NOTE: _rrf_score controls candidate selection only. │
│  It is NOT carried into the scoring stage.           │
│  base_score is always 0.0 in the unified path.       │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 5: ENRICH                                     │
│  Promote topic, stability, memory_type from          │
│  metadata._extra to top-level dict keys              │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 6: FILTER                                     │
│  Intent-specific: routing hints, status constraints,  │
│  type restrictions, reflection safety                │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 7: SCORE                                      │
│  score = 0.0 (base)                                  │
│         + profile_adjustment (±0.20 max)             │
│         + type_boost (per intent, ±0.30)             │
│         + 0.08 × recency (half-life decay)           │
│         + stability_boost (+0.03 / +0.01 / -0.02)   │
│         + reflection_penalty (-0.06)                 │
│         + graph_entity_boost (+0.15)                 │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 8: RERANK                                     │
│  Mode: enabled | shadow | disabled                   │
│  CompositeReranker: 5 signals, alpha-blended         │
│  OnnxCE: cross-encoder + alpha-blended               │
│  Shadow: computes but returns original order          │
└───────────────────────────┬─────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────┐
│  Stage 9: SELECT                                     │
│  Sort by score DESC, truncate to top_k               │
│  Convert to RetrievedMemory typed objects             │
└─────────────────────────────────────────────────────┘
```

### Context Assembly

`ContextAssembler.build()` produces the final Markdown string injected into the
system prompt. It assembles 7 sections with intent-aware token budgets:

| Section | Source | Budget Weight (fact_lookup) |
|---------|--------|---------------------------|
| Long-term Memory | `snapshots` table ("current" key) | 28% |
| Profile Memory | `ProfileStore.read_profile()` | 23% |
| Semantic Memories | Retrieved events (memory_type=semantic) | 20% |
| Entity Graph | `GraphAugmenter.build_graph_context_lines()` | 19% |
| Episodic Memories | Retrieved events (memory_type=episodic) | 5% |
| Reflection Memories | Retrieved events (reflection intent only) | 0% |
| Unresolved Tasks | Recent open task/decision events | 5% |

Budget allocation is two-pass: proportional first, then surplus redistributed.
Minimum 40 tokens per active section. Safety cap: total output <= `budget * 4`
characters.

---

<a id="knowledge-graph"></a>
## 6. Knowledge Graph

### Ontology

**33 entity types** organized into groups: People (PERSON), Systems (SYSTEM, SERVICE,
DATABASE, API), Concepts (CONCEPT, TECHNOLOGY, FRAMEWORK, PATTERN), Locations (LOCATION,
REGION, ENVIRONMENT), Organisational (PROJECT, ORGANIZATION), and 11 Agent-native types
(AGENT, USER, TASK, ACTION, OBSERVATION, MEMORY, SESSION, MESSAGE, DOCUMENT, TOOL, MODEL).

**22 relationship types:** 11 infrastructure predicates (WORKS_ON, USES, DEPENDS_ON,
etc.) and 11 agent-operational predicates (PERFORMS, EXECUTES, PRODUCES, etc.).

### Entity Classification

6-signal cascade with decreasing confidence:

| Signal | Confidence | Method |
|--------|-----------|--------|
| Regex patterns | 0.95 | Email, URL, version strings |
| Token keywords | 0.85 | Exact match against keyword sets |
| Phrase keywords | 0.85 | Substring match for multi-word phrases |
| Suffix heuristics | 0.75 | "-service", "-db", "-api" |
| Role keywords | 0.70 | Job titles and role indicators |
| Capitalization | 0.45 | PascalCase or ALL_CAPS |

Type refinement: `refine_type_from_predicate()` promotes UNKNOWN entities based on
predicate context (e.g., WORKS_ON subject -> PERSON). Never overwrites a classified type.

### Validation Rules

Open-world semantics: predicates without rules are always valid. When domain/range
constraints are violated, confidence is demoted by 0.5x but the triple is still
inserted. Violations do not block — this prevents false negatives from incomplete
ontology coverage.

### Dual-Mode Operation

When `graph_enabled=false`, `KnowledgeGraph()` creates a disabled stub where all
methods return empty results. The graph storage tables still exist in the schema
but receive no writes.

---

<a id="profile-and-belief-system"></a>
## 7. Profile and Belief System

### Data Model

5 profile sections: `preferences`, `stable_facts`, `active_projects`, `relationships`,
`constraints`. Each entry is a `BeliefRecord` with confidence scoring, evidence
tracking, and lifecycle status.

### Belief Lifecycle

```
Created (conf 0.65)
    │
    ├─ Re-observed ─── conf += 0.03
    │
    ├─ Conflicted ──── old -0.12, new -0.20
    │    │
    │    ├─ Auto-resolved (gap >= 0.25) ─── winner +0.08
    │    ├─ User-resolved ─── winner +0.08, loser -> stale
    │    └─ Needs user ─── awaiting reply
    │
    ├─ Retracted ──── status "retracted", text removed from list
    │
    ├─ Stale ─── conf < 0.4, no recent evidence
    │
    └─ Pinned ─── survives stale, reactivates
```

### Conflict Detection

`ConflictManager._conflict_pair()`: requires one value to have negation (`" not "` or
`"n't"`) and the other not, with >= 0.55 non-negation token overlap. This is a
conservative heuristic — it only fires on explicit contradictions, not semantic
disagreements.

### Auto-Resolution

Priority order:
1. `"live_correction"` source -> force user review (no auto-resolve)
2. Confidence gap >= 0.25 -> keep higher confidence
3. Temporal tiebreaker -> keep newer
4. Correction language markers -> keep new

### Circular Dependency

`ProfileStore`, `ConflictManager`, and `CorrectionOrchestrator` form a dependency
triangle:

```
ProfileStore ←── ConflictManager
     ↑                  │
     └── CorrectionOrchestrator
```

Resolution: post-construction wiring via `set_conflict_mgr()` and `set_corrector()`
called in `MemoryStore.__init__` after all three are constructed. This means
`ProfileStore` has `None` fields between construction and the setter calls.

---

<a id="procedural-memory"></a>
## 8. Procedural Memory (Strategies)

### The Learning Feedback Loop

```
Turn 1: guardrail fires (strategy_tag) -> agent recovers -> success
         |
    StrategyExtractor detects tagged activation + subsequent success
         |
    LLM summarizes recovery as WHEN/DON'T/DO pattern
         |
    StrategyAccess.save(strategy, confidence=0.5)

Turn 2+: ContextBuilder retrieves strategies (conf >= 0.3, limit 5)
         |
    Agent reads strategy in system prompt -> correct behavior
         |
    No guardrail fires -> confidence += 0.1
         |
    Strategy established (conf -> 0.9 over sessions)
```

### Storage

`strategies` table with `domain` and `task_type` indexes. CRUD via `StrategyAccess`
(synchronous, uses shared `sqlite3.Connection`).

### Confidence Dynamics

| Event | Delta | Bounds |
|-------|-------|--------|
| Clean turn (no guardrail) | +0.1 | max 1.0 |
| Guardrail fired again | -0.05 | min 0.0 |
| Pruning threshold | 0.1 | deleted |

---

<a id="composition-and-wiring"></a>
## 9. Composition and Wiring

### MemoryStore Construction Sequence

`MemoryStore.__init__` is the memory subsystem's internal composition root. Construction
order (simplified):

```
1.  Embedder (OpenAI > Local > Hash, with fallback)
2.  MemoryDatabase (SQLite, creates all 9 tables)
3.  EventClassifier
4.  EventCoercer (depends on: 3)
5.  MemoryExtractor (depends on: 4)
6.  ProfileStore (depends on: 2)
7.  RetrievalPlanner
8.  TokenBudgetAllocator
9.  MemoryMaintenance (depends on: 2)
10. Reranker (Composite or ONNX, based on config)
11. KnowledgeGraph (depends on: 2, conditional on graph_enabled)
12. EventDeduplicator (depends on: 4)
13. EventIngester (depends on: 4, 12, 11, 2, 1)
14. ConflictManager (depends on: 6, 2)
15. POST-WIRE: ProfileStore.set_conflict_mgr(14)
16. RetrievalScorer (depends on: 10)
17. GraphAugmenter (depends on: 11, 5, 13)
18. MemoryRetriever (depends on: 16, 17, 7, 2, 1)
19. ContextAssembler (depends on: 6, 18, 7, 17, 2)
20. EvalRunner
21. MemorySnapshot (depends on: 6, 2)
22. CorrectionOrchestrator (depends on: 6, 5, 13, 4, 14, 21)
23. POST-WIRE: ProfileStore.set_corrector(22)
24. ConsolidationPipeline (depends on: 5, 13, 6, 14, 21, 2)
```

### External Wiring (agent_factory.py)

```python
# Step 2: Memory store
memory = MemoryStore(workspace, memory_config=config.memory)

# Step 3.5: Strategy store (shares SQLite connection)
strategy_store = StrategyAccess(memory.db.connection)

# Step 4: Context builder receives both
context = ContextBuilder(workspace, memory=memory, strategy_store=strategy_store)

# Step 7: Consolidation orchestrator
consolidator = ConsolidationOrchestrator(memory=context.memory, ...)

# Step 13: Micro-extractor (conditional)
if config.memory.micro_extraction_enabled:
    micro_extractor = MicroExtractor(provider=provider, ingester=memory.ingester, ...)

# Step 13.2: Strategy extractor (always)
strategy_extractor = StrategyExtractor(store=strategy_store, provider=provider)
```

---

<a id="integration-with-agent-core"></a>
## 10. Integration with Agent Core

### Pre-Turn (MessageProcessor)

1. `conflict_mgr.handle_user_conflict_reply(content)` — checks if message resolves a conflict
2. `profile_mgr.apply_live_user_correction(content)` — detects live corrections
3. `conflict_mgr.ask_user_for_conflict(user_message)` — deferred conflict question
4. Consolidation trigger: if `unconsolidated >= memory.window` -> submit background task

### System Prompt Assembly (ContextBuilder)

1. `strategy_store.retrieve(limit=5, min_confidence=0.3)` -> "Relevant Strategies"
2. `memory.get_memory_context(query, retrieval_k, token_budget)` -> full memory context
3. `feedback_summary(memory.db)` -> feedback correction stats

### Post-Turn (MessageProcessor)

1. `micro_extractor.submit(user_msg, assistant_msg, tool_hints)` — background async
2. `strategy_extractor.extract_from_turn(tool_results_log, guardrail_activations)` — awaited

### Tools

Only `FeedbackTool` directly writes to memory (`db.event_store.insert_event()`).
Other tools contribute indirectly via tool hints that become provenance strings.

---

<a id="extension-points"></a>
## 11. Extension Points

### Adding a New Event Type

1. Add the type to `EventType` literal in `event.py`
2. Add to `EVENT_TYPES` frozenset in `constants.py`
3. Update `EventClassifier.normalize_memory_metadata()` for memory_type/stability mapping
4. Update `EventCoercer.infer_episodic_status()` if episodic
5. Update `RetrievalPlanner.retrieval_policy()` type_boost values
6. No changes to schema, ingester, retriever, or scorer

### Adding a New Embedder

1. Create a class satisfying the `Embedder` protocol (embed, embed_batch, dims, available)
2. Add selection logic in `MemoryStore.__init__` embedder cascade
3. No changes to EventStore, MemoryRetriever, or any other consumer

### Adding a New Reranker

1. Create a class satisfying the `Reranker` protocol (available, rerank, compute_rank_delta)
2. Add selection logic in `MemoryStore.__init__` reranker construction
3. No changes to RetrievalScorer or any other consumer

### Adding a New Profile Section

1. Add the key to `PROFILE_KEYS` in `constants.py`
2. Update `EventClassifier.default_topic_for_event_type()` if a mapping exists
3. Profile CRUD, snapshot rendering, and belief lifecycle automatically pick it up

---

<a id="known-technical-debt"></a>
## 12. Known Technical Debt

### Performance

| Issue | Location | Impact |
|-------|----------|--------|
| `TokenBudgetAllocator` ignores config | `store.py` line 119 TODO | `memory_section_weights` not wired |

**Resolved (PR#122):** Full table scan in `append_events()` replaced with targeted
PK lookup + FTS5 pre-filtering. Missing indexes on `events` and `edges` tables added.

### Dead Code and Unused Parameters

| Item | Location | Notes |
|------|----------|-------|
| `vector_backend` parameter | `MemoryStore.__init__` | Accepted but never read |
| `embedding_provider` parameter | `MemoryRetriever.retrieve()` | Accepted but never used |
| `recency_half_life_days` parameter | `MemoryRetriever.retrieve()` | Accepted but never forwarded |
| `EventIngester._embedder` | `ingester.py` | Stored but unused; embeddings always `None` |
| `ConflictManager._db` | `conflicts.py` | Stored but never used in any method |
| `MemoryExtractor.last_extraction_source` | `extractor.py` | Set but never read externally |
| `EventClassifier.distill_semantic_summary` | `classification.py` | Defined but never called in write path |
| `is_mixed` return from `classify_memory_type` | `classification.py` | Always discarded by callers |
| `register_alias()` | `entity_linker.py` | Never called anywhere in codebase |
| `_keywords.py` module | `graph/_keywords.py` | Entire module dead; `_extract_query_keywords` never imported |
| `_backend_stats_for_eval()` | `maintenance.py` | Returns hardcoded zeros |
| `reindex_from_structured_memory()` | `maintenance.py` | Returns hardcoded success without doing work |

### Design Issues

| Issue | Location | Notes |
|-------|----------|-------|
| Post-construction wiring | `store.py` lines ~97, ~112 | ProfileStore has None fields between construction and set_* calls |
| Private method cross-call | `consolidation_pipeline.py` line 222 | Calls `_ingest_graph_triples()` — private method of EventIngester |
| Encapsulation leak | `retriever.py` line 136 | Accesses `_graph_aug._read_events_fn` — private attribute of collaborator |
| `compute_rank_delta` result discarded | `scoring.py` lines 410-412 | Shadow mode computes delta but never logs or stores it |
| Snapshot rebuild discarded | `profile_correction.py` | `rebuild_memory_snapshot(write=False)` result not captured |
| Two different recency decay formulas | `retrieval_planner.py` vs `reranker.py` | True half-life vs simple exponential — inconsistent behavior |
| `EventStore.search_by_metadata` naming | `event_store.py` | `memory_type` parameter filters on `type` column, not memory_type |
| Schema coupling via reference | `constants.py` | `_CONSOLIDATE_MEMORY_TOOL` shares sub-schema objects with `_SAVE_EVENTS_TOOL` by Python reference |
| Backward-compat naming | `conflicts.py` line 77 | `profile_mgr` attribute name documented as backward-compat (violates prohibited-patterns) |
| `_norm` duplication | `graph.py` + `graph_traversal.py` | Same function defined in two files |
| `_db` in Protocol | `graph_traversal.py` | `_KnowledgeGraphProtocol` exposes private attribute in interface |

### RRF Score Not Carried to Final Ranking

`_fuse_results()` stores the RRF score in `item["_rrf_score"]`. `score_items()` reads
`item.get("score", 0.0)` as `base_score`. Since neither `search_vector` nor `search_fts`
sets a `"score"` key, `base_score` is always `0.0`. RRF controls which candidates enter
the pipeline (up to `candidate_k`) but contributes zero to the final numeric score.
Whether this is intentional design or an accidental null-base is undocumented.

---

<a id="testing-strategy"></a>
## 13. Testing Strategy

### Contract Tests (`tests/contract/`)

| Test File | What It Verifies |
|-----------|-----------------|
| `test_memory_contracts.py` | MemoryStore public interface: supersession, recency, dedup, high-salience, context assembly |
| `test_memory_wiring.py` | Construction: strategies DDL, connection sharing, post-construction wiring |
| `test_memory_data_contracts.py` | Cross-component schemas: write-read event schema, profile keys, memory types |
| `test_memory_constants.py` | Stability of PROFILE_KEYS, EVENT_TYPES, MEMORY_TYPES, STRATEGIES_DDL |

### Unit Tests (`tests/`)

Over 40 test files covering individual components: database CRUD, embedder protocols,
event model, ingestion, dedup, classification, coercion, retrieval, scoring, reranking,
profile, corrections, snapshot, knowledge graph, ontology, strategies, feedback, and
consolidation.

### Integration Tests (`tests/integration/`)

| Test File | What It Verifies |
|-----------|-----------------|
| `test_agent_memory_write.py` | Agent loop -> events persisted (requires API key) |
| `test_agent_memory_read.py` | Stored events appear in system prompt (requires API key) |
| `test_memory_retrieval_pipeline.py` | Embeddings + vector search + FTS fusion end-to-end |
| `test_profile_conflicts.py` | Conflict detection + resolution workflow |
| `test_knowledge_graph_ingest.py` | Knowledge graph ingestion |
| `test_consolidation_pipeline.py` | Full consolidation with real LLM (requires API key) |

### Key Testing Patterns

- **ScriptedProvider** for deterministic LLM responses in unit tests
- **Contract tests** verify behavioral invariants, not implementation details
- **Data contract tests** verify write-read schema compatibility across components
- **`@pytest.mark.llm`** marks tests requiring real API keys
