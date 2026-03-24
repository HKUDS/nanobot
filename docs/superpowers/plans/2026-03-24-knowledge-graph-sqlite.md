# Knowledge Graph SQLite Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the knowledge graph from networkx + JSON file to SQLite tables in `memory.db`. Remove networkx dependency. Enable graph by default.

**Architecture:** Replace `graph.py`'s networkx `DiGraph` with SQL queries against two new tables (`entities`, `edges`) in `UnifiedMemoryDB`. The graph's public API stays identical — only internals change. Entity classifier, linker, and ontology modules are untouched (pure logic, no storage dependency).

**Tech Stack:** Python 3.10+, SQLite, pytest.

---

## File Map

| Action | File | Task |
|--------|------|------|
| Modify | `nanobot/agent/memory/unified_db.py` | 1 |
| Rewrite | `nanobot/agent/memory/graph.py` | 2 |
| Modify | `nanobot/agent/memory/migration.py` | 2 |
| Modify | `nanobot/agent/memory/store.py` | 3 |
| Modify | `nanobot/agent/memory/rollout.py` | 3 |
| Modify | `tests/test_knowledge_graph.py` | 2 |
| Modify | `tests/test_unified_db.py` | 1 |
| No change | `nanobot/agent/memory/entity_classifier.py` | — |
| No change | `nanobot/agent/memory/entity_linker.py` | — |
| No change | `nanobot/agent/memory/ontology.py` | — |
| No change | `nanobot/agent/memory/ontology_rules.py` | — |
| No change | `nanobot/agent/memory/ontology_types.py` | — |
| No change | `nanobot/agent/memory/ingester.py` | — |
| No change | `nanobot/agent/memory/retriever.py` | — |

---

## Task 1: Add Graph Tables to UnifiedMemoryDB

**Goal:** Add `entities` and `edges` tables to the SQLite schema. Add CRUD methods for graph operations.

**Context:** These tables replace the networkx `DiGraph` + JSON persistence. The `entities` table stores nodes with type, aliases, and properties. The `edges` table stores directed relationships with confidence scores. Both are in the same `memory.db` file alongside events, profile, history, and snapshots.

**Files:**
- Modify: `nanobot/agent/memory/unified_db.py`
- Modify: `tests/test_unified_db.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_unified_db.py`:

```python
class TestGraphTables:
    def test_entities_table_exists(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "entities" in tables
        assert "edges" in tables
        db.close()

    def test_upsert_and_read_entity(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person", aliases="ali",
                         properties='{"dept": "eng"}',
                         first_seen="2026-01-01", last_seen="2026-03-01")
        entity = db.get_entity("alice")
        assert entity is not None
        assert entity["type"] == "person"
        assert entity["aliases"] == "ali"
        db.close()

    def test_get_entity_returns_none_for_missing(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        assert db.get_entity("nonexistent") is None
        db.close()

    def test_upsert_entity_updates_existing(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person", aliases="",
                         first_seen="2026-01-01", last_seen="2026-01-01")
        db.upsert_entity("alice", type="person", aliases="ali",
                         first_seen="2026-01-01", last_seen="2026-03-01")
        entity = db.get_entity("alice")
        assert entity["aliases"] == "ali"
        assert entity["last_seen"] == "2026-03-01"
        db.close()

    def test_add_and_read_edge(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("project_x", type="project")
        db.add_edge("alice", "project_x", relation="WORKS_ON",
                    confidence=0.9, event_id="e1", timestamp="2026-01-01")
        edges = db.get_edges_from("alice")
        assert len(edges) == 1
        assert edges[0]["target"] == "project_x"
        assert edges[0]["relation"] == "WORKS_ON"
        db.close()

    def test_get_edges_to(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("project_x", type="project")
        db.add_edge("alice", "project_x", relation="WORKS_ON")
        edges = db.get_edges_to("project_x")
        assert len(edges) == 1
        assert edges[0]["source"] == "alice"
        db.close()

    def test_get_neighbors(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("bob", type="person")
        db.upsert_entity("project_x", type="project")
        db.add_edge("alice", "project_x", relation="WORKS_ON")
        db.add_edge("bob", "project_x", relation="WORKS_ON")
        neighbors = db.get_neighbors("project_x", depth=1)
        names = {n["name"] for n in neighbors}
        assert "alice" in names
        assert "bob" in names
        db.close()

    def test_get_neighbors_depth_2(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice", type="person")
        db.upsert_entity("project_x", type="project")
        db.upsert_entity("python", type="technology")
        db.add_edge("alice", "project_x", relation="WORKS_ON")
        db.add_edge("project_x", "python", relation="USES")
        # From alice, depth=2 should reach python
        neighbors = db.get_neighbors("alice", depth=2)
        names = {n["name"] for n in neighbors}
        assert "project_x" in names
        assert "python" in names
        db.close()

    def test_search_entities(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice_smith", type="person", aliases="ali")
        db.upsert_entity("bob_jones", type="person")
        results = db.search_entities("alice", limit=5)
        assert len(results) >= 1
        assert results[0]["name"] == "alice_smith"
        db.close()

    def test_search_entities_by_alias(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.upsert_entity("alice_smith", type="person", aliases="ali, smithy")
        results = db.search_entities("ali", limit=5)
        assert len(results) >= 1
        db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_unified_db.py::TestGraphTables -v
```

- [ ] **Step 3: Add tables to schema and implement methods**

In `unified_db.py`, add to `_init_schema()`:

```sql
CREATE TABLE IF NOT EXISTS entities (
    name       TEXT PRIMARY KEY,
    type       TEXT DEFAULT 'unknown',
    aliases    TEXT DEFAULT '',
    properties TEXT DEFAULT '{}',
    first_seen TEXT DEFAULT '',
    last_seen  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS edges (
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    relation   TEXT NOT NULL,
    confidence REAL DEFAULT 0.7,
    event_id   TEXT DEFAULT '',
    timestamp  TEXT DEFAULT '',
    PRIMARY KEY (source, relation, target)
);
```

Add methods:

```python
# Graph entities
def upsert_entity(self, name: str, *, type: str = "unknown",
                  aliases: str = "", properties: str = "{}",
                  first_seen: str = "", last_seen: str = "") -> None
def get_entity(self, name: str) -> dict[str, Any] | None
def search_entities(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]

# Graph edges
def add_edge(self, source: str, target: str, *, relation: str,
             confidence: float = 0.7, event_id: str = "",
             timestamp: str = "") -> None
def get_edges_from(self, entity_name: str) -> list[dict[str, Any]]
def get_edges_to(self, entity_name: str) -> list[dict[str, Any]]

# Graph traversal
def get_neighbors(self, entity_name: str, *, depth: int = 1) -> list[dict[str, Any]]
```

The `get_neighbors` method uses a recursive CTE for BFS:

```sql
WITH RECURSIVE bfs(name, depth) AS (
    VALUES(?, 0)
    UNION
    SELECT CASE WHEN e.source = bfs.name THEN e.target ELSE e.source END, bfs.depth + 1
    FROM bfs
    JOIN edges e ON e.source = bfs.name OR e.target = bfs.name
    WHERE bfs.depth < ?
)
SELECT DISTINCT ent.* FROM bfs
JOIN entities ent ON ent.name = bfs.name
WHERE bfs.name != ?
```

- [ ] **Step 4: Run tests**

```bash
make lint && pytest tests/test_unified_db.py -v
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/memory/unified_db.py tests/test_unified_db.py
git commit -m "feat: add entities + edges tables to UnifiedMemoryDB

Graph storage tables with upsert, search, and BFS neighbor traversal
via recursive CTE. Replaces networkx DiGraph for knowledge graph.
"
```

---

## Task 2: Rewrite graph.py to Use SQLite

**Goal:** Replace networkx `DiGraph` + JSON persistence in `graph.py` with SQL queries against `UnifiedMemoryDB`. The public API stays identical. Add graph JSON migration to `migration.py`.

**Context:** `graph.py` currently has 608 lines using networkx. The rewrite delegates all storage to `UnifiedMemoryDB` methods from Task 1. The `ingest_event_triples()` method keeps its entity classification logic (calling `entity_classifier.py`) but writes to SQL instead of networkx. `get_related_entity_names_sync()` and `get_triples_for_entities_sync()` become thin wrappers around `db.get_neighbors()` and `db.get_edges_from()`/`db.get_edges_to()`.

**Files:**
- Rewrite: `nanobot/agent/memory/graph.py`
- Modify: `nanobot/agent/memory/migration.py`
- Modify: `tests/test_knowledge_graph.py`

- [ ] **Step 1: Write failing tests for the new graph**

Update `tests/test_knowledge_graph.py` to construct `KnowledgeGraph` with a `db` parameter instead of a `workspace` path. Keep the same test assertions — the API doesn't change, only the backend.

Key test constructor change:
```python
# Old:
graph = KnowledgeGraph(workspace=tmp_path)

# New:
from nanobot.memory.unified_db import UnifiedMemoryDB
db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
graph = KnowledgeGraph(db=db)
```

- [ ] **Step 2: Rewrite graph.py**

Replace the full file. The new `KnowledgeGraph`:
- Constructor: `__init__(self, db: UnifiedMemoryDB | None = None)`
- `enabled` = `db is not None`
- Remove `_graph: nx.DiGraph`, `_json_path`, `_load()`, `_save()`
- Remove `import networkx as nx`
- `upsert_entity()` → `self._db.upsert_entity(...)`
- `add_relationship()` → `self._db.add_edge(...)`
- `ingest_event_triples()` — keep entity classification logic, call `self._db.upsert_entity()` and `self._db.add_edge()` instead of networkx
- `get_entity()` → `self._db.get_entity(...)`
- `search_entities()` → `self._db.search_entities(...)`
- `get_neighbors()` → `self._db.get_neighbors(...)`
- `get_related_entity_names_sync()` — call `self._db.get_neighbors(name, depth=depth)` and extract names
- `get_triples_for_entities_sync()` — call `self._db.get_edges_from(name)` + `self._db.get_edges_to(name)` and format as triples
- `find_paths()` — implement with recursive CTE or remove (not used in production)
- `close()` → no-op (db lifecycle managed by store.py)
- `verify_connectivity()` → return `self.enabled`

Target: ~200-250 lines (down from 608).

- [ ] **Step 3: Add graph migration to migration.py**

In `migrate_to_sqlite()`, after migrating events/profile/history/snapshots, add:

```python
graph_file = memory_dir / "knowledge_graph.json"
if graph_file.exists():
    _migrate_graph(db, graph_file)
```

```python
def _migrate_graph(db: UnifiedMemoryDB, graph_file: Path) -> None:
    """Migrate knowledge_graph.json nodes and edges to SQLite."""
    try:
        data = json.loads(graph_file.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read {} — skipping", graph_file.name)
        return

    for node in data.get("nodes", []):
        name = node.get("id", "")
        if not name:
            continue
        db.upsert_entity(
            name,
            type=node.get("entity_type", "unknown"),
            aliases=node.get("aliases_text", ""),
            properties=json.dumps({
                k[5:]: v for k, v in node.items() if k.startswith("prop_")
            }),
            first_seen=node.get("first_seen", ""),
            last_seen=node.get("last_seen", ""),
        )

    for edge in data.get("edges", []):
        source = edge.get("source", "")
        target = edge.get("target", "")
        if not source or not target:
            continue
        db.add_edge(
            source, target,
            relation=edge.get("type", "RELATED_TO"),
            confidence=float(edge.get("confidence", 0.7)),
            event_id=edge.get("source_event_id", ""),
            timestamp=edge.get("timestamp", ""),
        )
```

Add `knowledge_graph.json` to the `.bak` rename list.

- [ ] **Step 4: Run tests**

```bash
make lint && pytest tests/test_knowledge_graph.py tests/test_migration.py -v
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/memory/graph.py nanobot/agent/memory/migration.py \
        tests/test_knowledge_graph.py tests/test_migration.py
git commit -m "refactor: rewrite KnowledgeGraph to use SQLite — remove networkx

Replace networkx DiGraph + JSON with SQL queries against UnifiedMemoryDB.
Public API unchanged. BFS via recursive CTE. Graph JSON migrated to
entities/edges tables. ~608 lines → ~250 lines.
"
```

---

## Task 3: Wire Graph in Store + Enable by Default

**Goal:** Update `store.py` to pass `db` to `KnowledgeGraph` instead of `workspace`. Change `graph_enabled` default to `True`. Remove `networkx` from dependencies.

**Files:**
- Modify: `nanobot/agent/memory/store.py`
- Modify: `nanobot/agent/memory/rollout.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update store.py**

Find the graph construction (lines 218-223):

```python
# Old:
graph_enabled = self.rollout.get("graph_enabled", False)
if graph_enabled:
    self.graph = KnowledgeGraph(workspace=workspace)
else:
    self.graph = KnowledgeGraph()

# New:
graph_enabled = self.rollout.get("graph_enabled", True)
if graph_enabled and self.db is not None:
    self.graph = KnowledgeGraph(db=self.db)
else:
    self.graph = KnowledgeGraph()
```

- [ ] **Step 2: Update rollout.py default**

Change `graph_enabled` default from `False` to `True`.

- [ ] **Step 3: Remove networkx from dependencies**

In `pyproject.toml`, remove `"networkx>=3.0,<4.0"`. Verify no other module imports networkx.

- [ ] **Step 4: Run full test suite**

```bash
make lint
pytest -x --ignore=tests/test_shell_safety.py -q --cov=nanobot --cov-fail-under=85
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/memory/store.py nanobot/agent/memory/rollout.py pyproject.toml
git commit -m "feat: enable knowledge graph by default — backed by SQLite

Graph now uses UnifiedMemoryDB instead of networkx + JSON. Enabled
by default (graph_enabled=True). Removed networkx dependency.
"
```

---

## Task 4: Final Validation

**Goal:** Run full checks, verify networkx is gone, update architecture docs.

- [ ] **Step 1: Run pre-push checks**

```bash
make lint
python -m mypy nanobot/
python scripts/check_imports.py
pytest --ignore=tests/test_shell_safety.py -q --cov=nanobot --cov-fail-under=85
```

- [ ] **Step 2: Verify networkx is gone**

```bash
grep -rn "import networkx\|from networkx" nanobot/ tests/
```
Expected: no output.

- [ ] **Step 3: Verify graph tables exist**

```bash
python -c "
from pathlib import Path
import tempfile
from nanobot.memory.unified_db import UnifiedMemoryDB
with tempfile.TemporaryDirectory() as d:
    db = UnifiedMemoryDB(Path(d) / 'test.db', dims=4)
    db.upsert_entity('alice', type='person')
    db.upsert_entity('project_x', type='project')
    db.add_edge('alice', 'project_x', relation='WORKS_ON')
    n = db.get_neighbors('alice', depth=1)
    print(f'Neighbors of alice: {[x[\"name\"] for x in n]}')
    db.close()
"
```

- [ ] **Step 4: Update architecture docs**

Add to `docs/architecture.md` under "Storage Layer (Post-Redesign)":

```markdown
- **Knowledge graph** — entities and edges stored in `memory.db` (SQLite tables).
  Replaced networkx + JSON persistence. BFS via recursive CTE. Enabled by default.
  Entity classification (`entity_classifier.py`) is rule-based, no LLM needed.
```

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: update architecture for SQLite-backed knowledge graph"
```
