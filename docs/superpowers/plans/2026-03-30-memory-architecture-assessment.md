# Memory Subsystem Architecture Assessment

> Deep evaluation of the nanobot memory module — architectural health,
> structural weaknesses, and a proposed target architecture.
>
> Date: 2026-03-30
> Status: Assessment (no code changes)

---

## Executive Summary

The memory subsystem is the largest module in nanobot: **40 files, 10,035 LOC** across
6 subpackages. It delivers real value — hybrid retrieval (vector + FTS5 + RRF),
knowledge graph, conflict resolution, profile management, and consolidation — all
backed by a single SQLite database.

**What's working well:** The external integration is clean. Memory is properly
injected via the composition root, consumers use TYPE_CHECKING imports, failures
degrade gracefully. The subpackage decomposition (`write/`, `read/`, `ranking/`,
`persistence/`, `graph/`) correctly separates concerns at a directory level.

**What's not working well:** The *internal* architecture has three deep structural
problems that the decomposition introduced or failed to resolve:

1. **`MemoryStore` is a 385-line composition root masquerading as a facade**, with
   23 lambda callbacks and 26 `_fn=` parameters used to paper over circular
   dependencies between subsystems.

2. **`UnifiedMemoryDB` is a kitchen-sink repository** — one class owns CRUD for
   events, profile, history, snapshots, entities, edges, strategies, FTS5, and
   vector search. Every subsystem depends on it directly, creating a hidden
   coupling hub.

3. **7 files exceed the 500 LOC hard limit** (profile_io: 732, conflicts: 591,
   entity_classifier: 590, context_assembler: 589, graph: 573, extractor: 510,
   unified_db: 502), all marked `size-exception`. This many exceptions indicate
   the decomposition didn't go deep enough — it split files without resolving the
   underlying responsibility tangles.

These are not code-quality nits. They are architectural problems that make the
module progressively harder to maintain, test, and extend. Each new feature
added to memory will worsen the callback graph and grow the oversized files.

**Recommendation:** A phased refactoring that introduces a proper Repository
pattern for `UnifiedMemoryDB`, replaces the lambda callback web with a
lightweight service locator or builder pattern in `MemoryStore`, and splits the
oversized files along their natural seams.

---

## Current Architecture Assessment

### What's Working

**1. Clean external boundary.** The memory subsystem is properly isolated from
the rest of the codebase. `agent_factory.py` constructs `MemoryStore` and injects
it into consumers. No cross-package instantiation. All external imports use
TYPE_CHECKING guards. Zero boundary violations detected.

**2. Correct subpackage decomposition.** The five subdirectories (`write/`,
`read/`, `ranking/`, `persistence/`, `graph/`) map to real bounded contexts:
ingestion pipeline, retrieval pipeline, reranking, profile lifecycle, and
knowledge graph. Each has its own `__init__.py` with focused exports.

**3. Solid retrieval pipeline.** The read path is well-designed: intent-based
query planning -> vector + FTS5 search -> RRF fusion -> multi-signal scoring
-> cross-encoder reranking -> token-budgeted context assembly. Each stage is
a separate class with clear inputs and outputs.

**4. Graceful degradation throughout.** Every external dependency (OpenAI
embeddings, ONNX reranker, knowledge graph) has a fallback path. Crash
barriers are consistently applied. The system works with just `HashEmbedder`
and no graph.

**5. Good test coverage for happy paths.** Contract tests verify public API
guarantees. Integration tests exercise end-to-end flows. Unit tests cover
core transformations (dedup, coercion, classification). ~35 test files cover
the subsystem.

### What's Not Working

#### Problem 1: MemoryStore is a Composition Root, Not a Facade

The docstring says "thin facade that composes focused subsystem modules." In
reality, `MemoryStore.__init__` is a **283-line construction sequence** that:

- Instantiates 15+ subsystem objects in dependency order
- Creates 23 lambda callbacks to break circular dependencies
- Passes 26 `_fn=` callback parameters across subsystem boundaries
- Has a `_ensure_assembler()` method that reconstructs the assembler lazily
  to support test monkeypatching via `__new__`

This is not a facade pattern — it's a composition root that also exposes
subsystem internals as public attributes (`store.db`, `store.ingester`,
`store.retriever`, `store.profile_mgr`, `store.conflict_mgr`, `store.graph`,
`store.snapshot`, `store.maintenance`, `store.extractor`, `store.eval_runner`).

**Why this is a problem:**

- Adding any new subsystem requires modifying `MemoryStore.__init__` and
  potentially threading new callbacks through existing subsystems.
- The lambda callbacks create an invisible dependency graph that's hard to
  reason about. Example: `ContextAssembler` receives `profile_section_lines_fn`
  which is a lambda calling `self._assembler._profile_section_lines` — the
  assembler receives a callback to its own method via the store.
- `MemorySnapshot` receives callbacks to `ContextAssembler` private methods
  (`_profile_section_lines`, `_recent_unresolved`), violating encapsulation.
- Test setup requires either constructing the full dependency graph or using
  `__new__` bypass hacks.

**Root cause:** The decomposition extracted classes from `MemoryStore` but didn't
extract the *wiring*. The original monolithic class had methods that called each
other freely. After extraction, those internal calls became lambda callbacks
threaded through the constructor. The circular dependencies were always there —
lambdas just made them invisible instead of fixing them.

#### Problem 2: UnifiedMemoryDB is a God Repository

`UnifiedMemoryDB` (502 LOC) is a single class that handles:

| Concern | Methods |
|---------|---------|
| Event CRUD | `insert_event`, `read_events` |
| Vector search | `search_vector` |
| Full-text search | `search_fts` |
| Metadata search | `search_by_metadata` |
| Profile CRUD | `read_profile`, `write_profile` |
| History CRUD | `append_history`, `read_history` |
| Snapshot CRUD | `read_snapshot`, `write_snapshot` |
| Entity CRUD | `upsert_entity`, `get_entity`, `search_entities` |
| Edge CRUD | `add_edge`, `get_edges_from`, `get_edges_to` |
| Graph traversal | `get_neighbors` |
| Schema init | `_init_schema` |
| Connection mgmt | `connection`, `close`, context manager |
| Strategies DDL | Exported as `STRATEGIES_DDL` constant |

Every subsystem imports and depends on `UnifiedMemoryDB` directly. It's the
most-imported module in the package — the hidden coupling hub of the entire
subsystem.

**Why this is a problem:**

- Any schema change to one table (e.g., adding a column to events) requires
  modifying `UnifiedMemoryDB`, which is imported by every subsystem. The blast
  radius of any change is the entire memory package.
- The class mixes storage concerns (event persistence) with query concerns
  (FTS5 search, vector KNN) with graph concerns (entity/edge CRUD, BFS
  traversal). These change for different reasons at different rates.
- There's no abstraction between subsystems and their storage. `EventIngester`
  calls `db.insert_event()` directly. `KnowledgeGraph` calls `db.upsert_entity()`
  directly. This makes it impossible to swap storage backends per concern
  (e.g., use a dedicated vector store while keeping SQLite for events).
- The `connection` property exposes the raw SQLite connection, allowing any
  consumer to bypass the repository entirely (used by `StrategyAccess`).

**Root cause:** `UnifiedMemoryDB` was designed as a "unified" database — the
single-SQLite-file decision (which is correct for deployment simplicity) was
conflated with "single class for all database operations." These are different
decisions. You can have one SQLite file with multiple repository classes, each
owning its table(s).

#### Problem 3: Seven Files Exceed the Hard Size Limit

| File | LOC | Marked |
|------|-----|--------|
| `persistence/profile_io.py` | 732 | size-exception |
| `write/conflicts.py` | 591 | size-exception |
| `graph/entity_classifier.py` | 590 | — |
| `read/context_assembler.py` | 589 | size-exception |
| `graph/graph.py` | 573 | — |
| `write/extractor.py` | 510 | — |
| `unified_db.py` | 502 | — |

The project's own rules say 500 LOC is a hard limit with extraction required
before adding code. Seven `size-exception` files suggest the decomposition
stopped before completing the job — it split the original `MemoryStore` monolith
into smaller classes, but several of those classes inherited multiple
responsibilities that need further separation.

**Why this is a problem:**

- `profile_io.py` (732 LOC) handles profile CRUD, belief lifecycle, metadata
  bookkeeping, confidence tracking, pin/stale management, AND contradiction
  detection. That's at least 3 distinct concerns.
- `conflicts.py` (591 LOC) handles conflict listing, auto-resolution, user-facing
  prompts, AND final resolution with database sync. The user-facing Q&A flow
  is a different concern from the resolution algorithm.
- `context_assembler.py` (589 LOC) handles context assembly, profile rendering,
  token budgeting, AND unresolved event scanning. The rendering logic is
  distinct from the assembly orchestration.

**Root cause:** The decomposition was file-oriented, not responsibility-oriented.
Files were extracted from the monolith and named after their primary function,
but secondary responsibilities came along for the ride because they shared
internal state.

#### Problem 4: Circular Dependencies Masked by Callbacks

The lambda callback pattern in `store.py` masks genuine circular dependencies:

```
ProfileStore → needs → ConflictManager (via conflict_mgr_fn callback)
ConflictManager → needs → ProfileStore (direct import + constructor param)

MemorySnapshot → needs → ContextAssembler._profile_section_lines (via callback)
ContextAssembler → needs → MemoryRetriever.retrieve (via callback)
MemoryRetriever → needs → RetrievalScorer → needs → ProfileStore

ProfileStore → needs → MemoryExtractor (via extractor_fn callback)
ProfileStore → needs → EventIngester (via ingester_fn callback)
ProfileStore → needs → MemorySnapshot (via snapshot_fn callback)
MemorySnapshot → needs → ProfileStore (direct dependency)
```

These form cycles:
- `ProfileStore ↔ ConflictManager` (mutual dependency)
- `ProfileStore → Snapshot → Assembler → ... → ProfileStore` (transitive cycle)
- `ProfileStore → Ingester → ... (writes) → ProfileStore (reads)` (data cycle)

**Why this is a problem:** Circular dependencies are a strong signal that
subsystem boundaries are drawn in the wrong places. The lambdas hide the cycles
from import-checking tools, but the conceptual coupling remains. Any change to
one side of a cycle risks breaking the other.

#### Problem 5: Inconsistent Abstraction Levels

Some subsystems use clean Protocol-based abstraction (e.g., `Embedder`, `Reranker`).
Others use raw `dict[str, Any]` flowing through the entire pipeline:

- Events are `dict[str, Any]` from extraction through ingestion through retrieval
  through scoring through assembly. The `MemoryEvent` Pydantic model exists but
  is used primarily for validation at the extraction boundary, then immediately
  converted back to a dict.
- Profile data is `dict[str, Any]` everywhere — no typed model.
- Metadata is a JSON-encoded `TEXT` column in SQLite, unpacked/repacked at
  every stage with `json.loads`/`json.dumps`.

This means type safety is nominal — the system passes dicts around and relies
on runtime key access, which mypy can't check and which fails silently when
keys are missing or misspelled.

#### Problem 6: Duplicated Constants and Definitions

Several constants are defined in multiple places:

- `PROFILE_KEYS` is defined in `store.py` (line 59), `context_assembler.py`
  (line 45), and `profile_io.py` (line 30).
- Status constants (`CONFLICT_STATUS_OPEN`, etc.) are defined in `conflicts.py`
  and re-exported through `store.py`.
- `EPISODIC_STATUS_RESOLVED` appears in both `context_assembler.py` and `store.py`.

This isn't just a DRY violation — it's a coupling indicator. When three different
files need the same constants, they're conceptually entangled in ways the
module structure doesn't reflect.

---

## Key Architectural Problems (Ranked by Severity)

### Critical

1. **MemoryStore callback web** — 23 lambdas / 26 callback params creating an
   invisible dependency graph that's fragile, hard to test, and impossible to
   reason about statically. This is the #1 maintainability risk.

2. **UnifiedMemoryDB god repository** — single class coupling all subsystems
   to all storage concerns. Prevents independent evolution and testing.

### High

3. **Circular dependencies between ProfileStore, ConflictManager, and Snapshot**
   — masked by callbacks but conceptually present. Root cause: profile lifecycle
   is split across too many classes that need each other.

4. **Seven oversized files** — the decomposition was incomplete. Secondary
   responsibilities need further extraction.

### Medium

5. **Dict-oriented data flow** — events and profile data flow as untyped dicts,
   losing type safety and making the system fragile to key changes.

6. **Duplicated constants** — `PROFILE_KEYS` and status constants defined in
   3+ places, indicating conceptual coupling not reflected in structure.

### Low

7. **Test gaps in concurrency, schema migration, and error recovery** — not
   immediate risks but will matter as the system grows.

---

## Research Findings: Relevant Modern Patterns

### Pattern 1: Repository per Aggregate (Domain-Driven Design)

The standard solution for the "god repository" problem. Each domain aggregate
gets its own repository class that encapsulates persistence logic:

```
EventRepository      — owns events table, FTS5, vector embeddings
ProfileRepository    — owns profile table
GraphRepository      — owns entities + edges tables
SnapshotRepository   — owns snapshots + history tables
StrategyRepository   — owns strategies table
```

All repositories share the same SQLite connection (injected), but each owns
its table schema, migrations, and query logic. This is how Django, SQLAlchemy,
and every mature ORM structures data access.

**Applicability:** Direct. `UnifiedMemoryDB` should be split into focused
repositories that share a connection manager.

### Pattern 2: Builder Pattern for Complex Object Construction

When a composition root has 15+ dependencies with ordering constraints and
circular references, the Builder pattern isolates construction complexity:

```python
class MemorySystemBuilder:
    def __init__(self, workspace, config): ...
    def build(self) -> MemorySystem:
        db = self._build_db()
        repos = self._build_repositories(db)
        services = self._build_services(repos)
        return MemorySystem(repos, services)
```

**Applicability:** Direct replacement for `MemoryStore.__init__`. Separates
"how to construct" from "what to expose."

### Pattern 3: Mediator for Cross-Cutting Operations

When multiple services need to collaborate on a single operation (e.g.,
profile update triggers conflict check, snapshot rebuild, and event
ingestion), a Mediator coordinates without circular dependencies:

```python
class ProfileLifecycleMediator:
    """Coordinates profile changes across services."""
    def __init__(self, profile_repo, conflict_service, snapshot_service): ...
    async def apply_correction(self, field, old, new): ...
```

**Applicability:** Resolves the ProfileStore ↔ ConflictManager ↔ Snapshot
circular dependency by extracting the coordination into a dedicated class
that depends on all three (one-way), rather than having them depend on
each other.

### Pattern 4: Typed Domain Events Instead of Dicts

Replace `dict[str, Any]` with frozen dataclasses or Pydantic models at
aggregate boundaries:

```python
@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    id: str
    summary: str
    memory_type: MemoryType
    relevance_score: float
    source: str
    metadata: MemoryMetadata
```

**Applicability:** Replaces the dict-oriented data flow in the retrieval
pipeline. Type checkers can verify field access. Missing fields fail at
construction, not at consumption.

### Pattern 5: Connection Manager (Shared Infrastructure)

A lightweight class that owns the SQLite connection and provides it to
repositories:

```python
class MemoryDatabase:
    """Owns the SQLite connection, loads extensions, runs migrations."""
    def __init__(self, path: Path, dims: int): ...

    @property
    def connection(self) -> sqlite3.Connection: ...

    def ensure_schema(self) -> None: ...
```

Repositories receive this, not the raw connection. The schema is defined
by the repositories themselves (each declares its DDL), and the connection
manager runs them in order.

**Applicability:** Direct. Separates "manage the database" from "access
specific tables."

---

## Proposed Target Architecture

### Design Principles

1. **One class, one reason to change** — no class handles both CRUD and
   coordination, or both storage and rendering.
2. **No circular dependencies** — if A needs B and B needs A, extract the
   shared concern into C that both depend on.
3. **Typed boundaries** — domain objects at every subsystem boundary, dicts
   only inside the persistence layer.
4. **Repository per aggregate** — each domain concept owns its storage.
5. **Explicit construction** — builder pattern instead of lambda callbacks.

### Module Structure

```
memory/
├── __init__.py              # Public API: MemorySystem, MemoryEvent, Embedder
├── system.py                # MemorySystem — slim facade (delegates only)
├── builder.py               # MemorySystemBuilder — construction logic
│
├── db/                      # Storage layer (repositories)
│   ├── __init__.py
│   ├── connection.py        # MemoryDatabase — connection mgmt, schema init
│   ├── event_repo.py        # EventRepository — events + FTS5 + vector
│   ├── profile_repo.py      # ProfileRepository — profile table CRUD
│   ├── graph_repo.py        # GraphRepository — entities + edges + traversal
│   ├── snapshot_repo.py     # SnapshotRepository — snapshots + history
│   └── strategy_repo.py     # StrategyRepository — strategies table
│
├── model/                   # Domain models (typed, frozen)
│   ├── __init__.py
│   ├── event.py             # MemoryEvent (existing Pydantic model, enhanced)
│   ├── profile.py           # ProfileData, BeliefRecord, BeliefMetadata
│   ├── retrieval.py         # RetrievedMemory, RetrievalIntent, RetrievalPolicy
│   └── graph.py             # Entity, Relationship, Triple (existing types)
│
├── write/                   # Ingestion pipeline (unchanged structure)
│   ├── __init__.py
│   ├── extractor.py         # MemoryExtractor
│   ├── micro_extractor.py   # MicroExtractor
│   ├── ingester.py          # EventIngester (uses EventRepository)
│   ├── coercion.py          # EventCoercer
│   ├── classification.py    # EventClassifier
│   └── dedup.py             # EventDeduplicator
│
├── read/                    # Retrieval pipeline (unchanged structure)
│   ├── __init__.py
│   ├── retriever.py         # MemoryRetriever (uses EventRepository)
│   ├── retrieval_planner.py # RetrievalPlanner
│   ├── scoring.py           # RetrievalScorer
│   ├── graph_augmentation.py# GraphAugmenter (uses GraphRepository)
│   └── context_assembler.py # ContextAssembler (rendering only, <400 LOC)
│
├── ranking/                 # Reranking (unchanged)
│   ├── __init__.py
│   ├── reranker.py          # CompositeReranker
│   └── onnx_reranker.py     # OnnxCrossEncoderReranker
│
├── profile/                 # Profile lifecycle (replaces persistence/)
│   ├── __init__.py
│   ├── store.py             # ProfileStore — CRUD only (<300 LOC)
│   ├── belief.py            # BeliefLifecycle — confidence, pin, stale (<300 LOC)
│   ├── conflict.py          # ConflictDetector — detection only
│   ├── resolution.py        # ConflictResolver — auto + user resolution
│   ├── correction.py        # CorrectionOrchestrator (existing)
│   └── snapshot.py          # MemorySnapshot (existing)
│
├── graph/                   # Knowledge graph (unchanged structure)
│   ├── __init__.py
│   ├── graph.py             # KnowledgeGraph (uses GraphRepository)
│   ├── entity_classifier.py # Split: classifier + keyword scorer (<400 each)
│   ├── entity_linker.py     # EntityLinker
│   ├── ontology_types.py    # Type definitions
│   └── ontology_rules.py    # Validation rules
│
├── consolidation.py         # ConsolidationPipeline (existing)
├── maintenance.py           # MemoryMaintenance (existing)
├── embedder.py              # Embedder protocol + implementations (existing)
├── strategy.py              # StrategyAccess (uses StrategyRepository)
├── strategy_extractor.py    # StrategyExtractor (existing)
├── token_budget.py          # TokenBudgetAllocator (existing)
├── constants.py             # Shared constants — SINGLE source of truth
└── _text.py                 # Text utilities (existing)
```

### Key Changes

**1. `UnifiedMemoryDB` → `db/` package with focused repositories**

```python
# db/connection.py
class MemoryDatabase:
    """Owns the SQLite connection and schema lifecycle."""
    def __init__(self, db_path: Path, *, dims: int) -> None: ...
    @property
    def conn(self) -> sqlite3.Connection: ...
    def ensure_schema(self, ddl_providers: list[SchemaProvider]) -> None: ...
    def close(self) -> None: ...

# db/event_repo.py
class EventRepository:
    """Events + FTS5 + vector search."""
    SCHEMA = "CREATE TABLE IF NOT EXISTS events ..."
    def __init__(self, db: MemoryDatabase, embedder: Embedder) -> None: ...
    def insert(self, event: MemoryEvent, embedding: list[float] | None) -> None: ...
    def read(self, *, limit: int, status: str | None, type: str | None) -> list[MemoryEvent]: ...
    def search_vector(self, embedding: list[float], k: int) -> list[MemoryEvent]: ...
    def search_fts(self, query: str, k: int) -> list[MemoryEvent]: ...
```

Each repository declares its own schema DDL. The connection manager collects
and executes them at startup. Repositories return typed domain objects, not
raw dicts.

**2. `MemoryStore` → `MemorySystem` (slim facade) + `MemorySystemBuilder`**

```python
# system.py
class MemorySystem:
    """Slim facade — exposes subsystem APIs. No construction logic."""
    def __init__(
        self,
        *,
        events: EventRepository,
        profiles: ProfileRepository,
        graphs: GraphRepository,
        ingester: EventIngester,
        retriever: MemoryRetriever,
        profile_lifecycle: ProfileLifecycle,
        consolidation: ConsolidationPipeline,
        maintenance: MemoryMaintenance,
        snapshot: MemorySnapshot,
    ) -> None:
        self.events = events
        self.profiles = profiles
        self.ingester = ingester
        self.retriever = retriever
        # ... etc

    async def get_memory_context(self, *, query: str, ...) -> str:
        return await self._assembler.build(query=query, ...)

# builder.py
class MemorySystemBuilder:
    """Constructs the full memory system. Replaces MemoryStore.__init__."""
    def __init__(self, workspace: Path, config: MemoryConfig) -> None: ...
    def build(self) -> MemorySystem: ...
```

The builder handles construction order and dependency resolution. The facade
is a data holder with delegation methods. No lambdas needed because the builder
constructs everything in the right order and passes concrete references.

**3. Profile lifecycle restructured**

The circular dependency between ProfileStore, ConflictManager, and Snapshot is
resolved by splitting ProfileStore into focused classes and using a mediator:

```python
# profile/store.py — pure CRUD, no lifecycle logic
class ProfileStore:
    def __init__(self, repo: ProfileRepository) -> None: ...
    def read(self) -> ProfileData: ...
    def write(self, data: ProfileData) -> None: ...
    def add_belief(self, section: str, text: str) -> BeliefRecord: ...

# profile/conflict.py — detection only, no resolution
class ConflictDetector:
    def detect(self, old: str, new: str) -> Conflict | None: ...
    def list_open(self) -> list[Conflict]: ...

# profile/resolution.py — resolution logic
class ConflictResolver:
    def __init__(self, store: ProfileStore, detector: ConflictDetector) -> None: ...
    def auto_resolve(self, conflict: Conflict) -> Resolution: ...
    def resolve_with_user(self, conflict: Conflict, choice: str) -> Resolution: ...
```

No circular dependencies: `ConflictResolver` depends on `ProfileStore` and
`ConflictDetector`. Neither of those depends back on the resolver.

**4. Typed domain models replace dict flow**

```python
# model/retrieval.py
@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    id: str
    summary: str
    memory_type: Literal["semantic", "episodic", "reflection"]
    relevance_score: float
    recency_score: float
    source: str
    topic: str | None
    status: str
    confidence: float
    metadata: dict[str, Any]  # only for pass-through, not for key access
```

The retrieval pipeline returns `list[RetrievedMemory]` instead of
`list[dict[str, Any]]`. Type checkers can verify every field access.

### Dependency Graph (Target)

```
                    MemorySystemBuilder
                          │
                          ▼
                     MemorySystem
                    ╱     │     ╲
                   ╱      │      ╲
            Ingestion  Retrieval  Profile
            Pipeline   Pipeline   Lifecycle
               │          │          │
               ▼          ▼          ▼
         EventRepo   EventRepo   ProfileRepo
               │          │          │
               └──────────┴──────────┘
                          │
                          ▼
                    MemoryDatabase
                    (shared conn)
```

All arrows point **downward**. No cycles. Repositories share the connection
but own their own tables. Subsystems depend on repositories, not on each other.

---

## Migration Plan

### Phase 0: Preparation (Low Risk)

**Goal:** Consolidate duplicated constants, add typed models alongside dicts.

1. **Consolidate constants into `constants.py`** — move `PROFILE_KEYS`,
   all status constants, memory types, stability levels into one file.
   Update all imports. Pure refactoring, no behavior change.

2. **Add `model/` package with typed dataclasses** — create `RetrievedMemory`,
   `ProfileData`, `BeliefRecord` as typed models. Initially, convert to/from
   dicts at boundaries. No subsystem changes needed.

3. **Add contract tests for cross-component data contracts** — verify that
   what the write path produces matches what the read path expects. These
   tests protect the migration.

**Estimated scope:** ~200 LOC new, ~50 LOC modified. No behavioral changes.

### Phase 1: Extract Repository Layer (Medium Risk)

**Goal:** Split `UnifiedMemoryDB` into focused repositories sharing a connection.

1. **Create `db/connection.py`** — `MemoryDatabase` class that owns the SQLite
   connection, loads sqlite-vec, and runs schema DDL.

2. **Create `db/event_repo.py`** — move event CRUD + FTS5 + vector search from
   `UnifiedMemoryDB`. Wire `EventIngester` and `MemoryRetriever` to use
   `EventRepository` instead of `UnifiedMemoryDB`.

3. **Create `db/profile_repo.py`** — move profile CRUD from `UnifiedMemoryDB`.
   Wire `ProfileStore`.

4. **Create `db/graph_repo.py`** — move entity + edge CRUD + traversal. Wire
   `KnowledgeGraph`.

5. **Create `db/snapshot_repo.py`** — move snapshot + history CRUD.

6. **Create `db/strategy_repo.py`** — move strategy DDL and wire `StrategyAccess`.

7. **Delete `UnifiedMemoryDB`** and update all consumers to use the new
   repositories directly in the same commit. No compatibility shim — this
   project has no external consumers (per prohibited-patterns.md). Grep for
   `UnifiedMemoryDB` across the repo — zero matches required.

**Estimated scope:** ~600 LOC new (repositories), ~400 LOC modified (consumers).
Each step is independently testable and committable.

### Phase 2: Resolve Profile Circular Dependencies (Medium Risk)

**Goal:** Split `profile_io.py` (732 LOC) and resolve the ProfileStore ↔
ConflictManager cycle.

1. **Extract `profile/belief.py`** — belief lifecycle, confidence tracking,
   pin/stale management. ~250 LOC out of `profile_io.py`.

2. **Split `conflicts.py` into `conflict.py` + `resolution.py`** — separate
   detection from resolution. Detection is pure logic; resolution orchestrates
   profile writes.

3. **Restructure dependencies** — `ConflictResolver` depends on `ProfileStore`
   and `ConflictDetector` (not the other way around). Remove the
   `conflict_mgr_fn` callback from `ProfileStore`.

4. **Update builder** — construction order in `MemorySystemBuilder` is:
   ProfileStore → ConflictDetector → ConflictResolver → CorrectionOrchestrator.
   No circular dependencies, no lambda callbacks.

**Estimated scope:** ~100 LOC new, ~400 LOC reorganized. Callbacks reduced by ~8.

### Phase 3: Replace MemoryStore with Builder + Facade (Medium Risk)

**Goal:** Replace the 385-line `MemoryStore.__init__` with a builder.

1. **Create `builder.py`** — `MemorySystemBuilder` with a `build()` method
   that returns `MemorySystem`.

2. **Create `system.py`** — `MemorySystem` as a slim facade. Constructor takes
   pre-built subsystems (no construction logic, no callbacks).

3. **Update `agent_factory.py`** — replace `MemoryStore(workspace, config)`
   with `MemorySystemBuilder(workspace, config).build()`.

4. **Delete `MemoryStore`** and update all references (`agent_factory.py`,
   `context/context.py`, tests, etc.) to use `MemorySystem` in the same commit.
   No deprecation wrapper, no re-export alias — per prohibited-patterns.md,
   the old name must not survive the commit. Grep for `MemoryStore` across
   the repo — zero matches required (excluding docs/history).

**Estimated scope:** ~200 LOC new, ~150 LOC removed. Lambda count drops to 0.

### Phase 4: Split Remaining Oversized Files (Low Risk)

**Goal:** Get all files under 500 LOC.

1. **`context_assembler.py` (589 LOC)** — extract profile rendering helpers
   into `read/profile_renderer.py`. Assembler becomes orchestration only.

2. **`entity_classifier.py` (590 LOC)** — extract keyword scoring into
   `graph/keyword_scorer.py`. Classifier becomes a thin dispatcher.

3. **`graph.py` (573 LOC)** — extract triple ingestion into
   `graph/triple_ingester.py`. Graph becomes entity/relationship CRUD +
   traversal only.

4. **`extractor.py` (510 LOC)** — extract heuristic extraction into
   `write/heuristic_extractor.py`. Main extractor focuses on LLM-based
   extraction.

**Estimated scope:** ~400 LOC reorganized per file. Pure mechanical extraction.

### Phase 5: Typed Data Flow (Low Risk, Ongoing)

**Goal:** Replace `dict[str, Any]` with typed models at subsystem boundaries.

1. Start with the retrieval pipeline (highest traffic): `MemoryRetriever` returns
   `list[RetrievedMemory]` instead of `list[dict]`.
2. Move to the ingestion pipeline: `EventIngester.append_events` accepts
   `list[MemoryEvent]` instead of `list[dict]`.
3. Profile operations use `ProfileData` model.

This phase can proceed incrementally — each boundary conversion is independent.

---

## Risks, Tradeoffs, and Open Questions

### Risks

1. **Test fragility during migration** — Phases 1-3 change internal structure
   significantly. Mitigation: add contract tests in Phase 0 that verify
   behavioral invariants, not implementation details. Run these after every
   phase.

2. **Performance regression from repository layer** — Adding a layer between
   subsystems and SQLite adds function call overhead. Mitigation: the overhead
   is negligible for SQLite operations (I/O-bound). Benchmark if concerned.

3. **Callers using `store.db.*` directly** — If anything outside `memory/`
   uses `store.db.insert_event()` directly, that path breaks. Mitigation:
   grep for `store.db.` outside `memory/` before starting. Update all callers
   to use the new repository APIs in the same commit — no shims (per
   prohibited-patterns.md, this project has no external consumers).

### Tradeoffs

1. **More files in `db/` package** — 6 repository files vs 1 `unified_db.py`.
   Tradeoff: more files but each is small (~100-150 LOC), focused, and
   independently testable. Consistent with the project's own pattern of
   preferring focused modules.

2. **Builder adds a class** — `MemorySystemBuilder` is a new class that exists
   only for construction. Tradeoff: one more class, but it replaces 23 lambdas
   and 283 lines of `__init__` spaghetti. Net reduction in complexity.

3. **`model/` package adds overhead** — typed dataclasses at boundaries mean
   conversion at the persistence layer. Tradeoff: runtime cost is trivial
   (dataclass construction is C-speed in Python 3.12+). Type safety benefit
   is substantial for an LLM-maintained codebase where there's no human
   reviewing field access correctness.

### Open Questions

1. **Should the `db/` package use an ORM or stay raw SQLite?** Recommendation:
   stay raw. The schema is stable, queries are simple, and an ORM adds
   dependency weight for no clear benefit.

2. **Should repositories be async?** Recommendation: keep them synchronous
   (current pattern), wrap with `asyncio.to_thread()` at the service layer.
   SQLite doesn't benefit from async I/O.

3. **Should the `Embedder` protocol move into `db/` since it's used by
   `EventRepository`?** Recommendation: keep it in `memory/embedder.py`.
   Embedding is a domain concern (choosing the right model, dimensions),
   not a storage concern. The repository receives an embedder, doesn't own one.

4. **What about the `eval_runner` import inside `MemoryStore.__init__`?**
   The eval module (`nanobot/eval/`) should not be constructed inside the
   memory subsystem. Move its construction to `agent_factory.py` or a
   dedicated eval setup function.

---

## Conclusion

The memory subsystem delivers significant functionality, but the internal
architecture has accumulated structural debt through the decomposition process.
The three core problems — callback-laced composition root, god repository, and
oversized files with mixed responsibilities — are interconnected and worsen
with each feature addition.

The proposed migration is incremental (5 phases), each independently valuable
and committable. Phase 1 (repository extraction) delivers the most architectural
improvement per effort. Phase 3 (builder + facade) eliminates the callback web.
Phases 2 and 4 are straightforward file splits.

The target architecture follows standard patterns (Repository, Builder, Mediator)
that any future LLM session can understand without reading extensive documentation.
This is critical for an LLM-maintained codebase — the more standard the patterns,
the less likely future sessions are to introduce drift.
