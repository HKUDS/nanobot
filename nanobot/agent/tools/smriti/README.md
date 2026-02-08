# 🧠 Smriti — Durable Memory Engine for AI Agents (built for Nanobot)

Smriti is a **lightweight, auditable, file-based memory engine** designed for long-running AI agents.
It is the long-term memory layer **built for Nanobot**.

**Design goals**

> **Human-readable  but also fast.**

All memory is stored in **Markdown as the source of truth**, with **SQLite (+ FTS5)** providing fast recall, ranking, and filtering.

---

## Why Smriti

Most agent memory systems are opaque (vector DBs, embeddings, proprietary stores). Smriti is different:

* ✅ Open memory with a text editor
* ✅ Git-diff memory changes
* ✅ Crash-safe writes (append-only + atomic rewrites)
* ✅ Deterministic behavior you can debug

Designed for **years-long agent operation**, not demos.

---

## Core guarantees

* **Markdown is canonical** — SQLite is an index/cache, never the authority
* **Append-only writes** — no in-place mutation of history
* **Soft deletion** — “forget” moves entries to `.trash/` for recovery
* **Stable IDs** — every memory has a permanent `^<10-hex>` identifier
* **Deterministic behavior** — same input → same result

---

## Storage layout

```text
workspace/
└── memory/
    ├── YYYY-MM-DD.md        # daily memory (append-only)
    ├── MEMORY.md            # curated long-term memory
    ├── index.sqlite3        # SQLite index (FTS5 if available)
    └── .trash/
        └── YYYY-MM-DD.md    # soft-deleted memories
```

You can delete `index.sqlite3` at any time — it will be rebuilt automatically.

---

## Memory model

Each stored memory has:

| Field    | Meaning                                    |
| -------- | ------------------------------------------ |
| `id`     | Stable ID: `^a1b2c3d4e5`                   |
| `kind`   | `fact`, `note`, `todo`, `pref`, `decision` |
| `scope`  | `daily` or `long`                          |
| `text`   | Raw human text                             |
| `tags`   | Extracted from `#hashtags`                 |
| `people` | Extracted from `@mentions`                 |
| `source` | Markdown file path                         |

Tags and people are **auto-extracted** — no schema required.

---

## Public API

Smriti is usable in two ways:

1. **Python library API** (`MemoryStore`) — direct use in scripts/services.
2. **Agent tool wrapper** (Nanobot) — typically exposes `action=...` style calls that map to the same operations.

### Python library API

```python
from nanobot.agent.tools.smriti import MemoryStore

store = MemoryStore(workspace="./workspace")
```

#### remember

```python
# Store a richly annotated todo
mid = store.remember(
    "Review PR #234 for auth module @alice #work #coding due:2026-02-10",
    kind="todo",
    scope="daily",
)
```

* Appends one line to Markdown (`YYYY-MM-DD.md` for `daily`, `MEMORY.md` for `long`)
* Extracts and normalizes `#tags` and `@people` for structured search
* Indexes full text + metadata into SQLite (and FTS5 if available)
* Returns a stable ID like `a1b2c3d4e5` (stored in files as `^a1b2c3d4e5`)

More examples:

```python
# Long-term preference
store.remember(
    "User prefers dark mode in VS Code; Fira Code 14pt; auto-save on.",
    kind="pref",
    scope="long",
)

# Decision with rationale + structured tags
store.remember(
    "DECISION: isolate family memories by separate instances; avoid shared data #privacy #architecture",
    kind="decision",
    scope="long",
)
```

---

#### recall

```python
hits = store.recall("scope:daily kind:todo #work", limit=5)
```

More examples:

```python
# Person + kind filter
hits = store.recall("@alice kind:todo scope:daily", limit=10)

# Long-term free-text
hits = store.recall("scope:long thermodynamics entropy", limit=3)

# Direct ID lookup
hits = store.recall("^a1b2c3d4e5", limit=1)

# Include soft-deleted items (search trash)
hits = store.recall("#privacy decision", limit=5, include_trash=True)
```

Notes:

* Uses SQLite FTS5 if available
* Falls back to file scan if not
* Supports structured + free-text queries

---

#### promote

```python
store.promote("^a1b2c3d4e5")
```

* Moves an item from daily → long-term (`MEMORY.md`)
* Updates scope in the index
* Keeps history intact

Copy instead of move:

```python
store.promote("^a1b2c3d4e5", remove=False)
```

---

#### soft_forget / restore

```python
store.soft_forget("^a1b2c3d4e5")
store.restore("^a1b2c3d4e5")
```

* Forget moves the line to `.trash/`
* Restore re-activates it
* No permanent deletion

---

#### listing + context packing

```python
print(store.list_recent(limit=20))
print(store.list_trash(limit=20))

# Compact context block for prompting
ctx = store.get_memory_context(long_chars=1200, recent_n=10)
```

---

#### agent tag hygiene

```python
# Inspect most common tags/people
v = store.vocab(rows=5000)

# Suggest existing tags to reuse for a new entry
tags = store.suggest_tags(
    "note: discuss thermodynamics entropy with alex today",
    max_tags=2,
    min_count=2,
)
```

### Agent tool wrapper (Nanobot-style)

Many agent integrations expose a wrapper that maps directly to `MemoryStore`:

```python
memory(action="remember", text="Review PR #234 @alice #work #coding", kind="todo", scope="daily")
memory(action="recall",   text="scope:daily kind:todo @alice", limit=10)
memory(action="promote",  mid="^a1b2c3d4e5")
memory(action="forget",   mid="^a1b2c3d4e5")
memory(action="restore",  mid="^a1b2c3d4e5")
```

---

## Query syntax

Smriti supports a small **query language** for recall:

```text
kind:fact|note|todo|pref|decision
scope:daily|long|pinned
#tag
@person
^<memory_id>
free text terms
```

### Examples

```text
kind:todo scope:daily
scope:long #physics
@alice kind:decision
#work #coding review
^a1b2c3d4e5
```

All filters compose cleanly.

---

## Screenshot-ready reference (agent view)

```
┌────────────────────────────────────────────────────────────┐
|🧠 SMRITI — MEMORY ENGINE                                  |
├────────────────────────────────────────────────────────────┤
│ FORMAT   : Markdown (truth) + SQLite (index)               │
│ PATH     : workspace/memory/                               │
│ IDS      : ^abcdef1234                                     │
├────────────────────────────────────────────────────────────┤
│ ACTIONS                                                    │
│  remember   → store memory                                 │
│  recall     → search memory                                │
│  list       → recent entries                               │
│  forget     → soft delete (to .trash)                      │
│  restore    → recover from trash                           │
│  promote    → daily → long-term                            │
├────────────────────────────────────────────────────────────┤
│ KINDS            SCOPES                                    │
│  fact            daily                                     │
│  note            long                                      │
│  todo                                                      │
│  pref                                                      │
│  decision                                                  │
├────────────────────────────────────────────────────────────┤
│ QUERY TOKENS                                               │
│  kind:todo scope:daily                                     │
│  #tag   @person   ^id                                      │
│  free-text (FTS5 ranked)                                   │
└────────────────────────────────────────────────────────────┘
```

---

## Agent-friendly features

* **Tag reuse suggestions** (`suggest_tags()`)
* **Vocabulary introspection** (`vocab()`)
* **Context packing** (`get_memory_context()`)

Designed to be called repeatedly inside an agent loop without drift.

---

## Benchmarking

Smriti includes a **minimal** deterministic **benchmark harness** (`smriti.bench`) can be used to validate core guarantees and measure performance:
```bash
python -m nanobot.agent.tools.smriti.bench --clean --items 2000 --queries 400
```

It validates:

* Recall@K / Top-1 / MRR
* Promote invariants
* Soft-delete correctness
* Tag hygiene
* Latency (write + query)

This is an invariant contract.

---

## Philosophy

Smriti is intentionally **not**:

* ❌ a vector database
* ❌ an embedding store
* ❌ an opaque memory black box

It **is**:

* A durable cognitive ledger
* A debuggable memory substrate
* A system you can trust at 3 AM

If your agent forgets something, **you can see why**.

---

## License

MIT — use it, fork it, evolve it.

---

## Name and Meaning

> **Smṛti** (स्मृति) — *Sanskrit for “memory”*  
> That which is remembered.

Not recall probability.  
Not embeddings.  
Not vector scores.

Just memory.  
Clean. Durable. Human.
