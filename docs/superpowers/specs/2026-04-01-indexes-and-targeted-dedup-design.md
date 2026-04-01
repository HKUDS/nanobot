# Missing Indexes + Targeted SQL Dedup

> Design spec for Priority 2+3 from the memory retrospective.
> Date: 2026-04-01. Status: Approved.

## Problem

1. **Missing indexes:** The events table has no indexes beyond the PK. All filtered
   queries (`WHERE type = ?`, `WHERE status = ?`, `ORDER BY timestamp DESC`) do full
   table scans. The edges table lacks an index on `target`, making `get_edges_to()`
   and BFS traversal scan the full table on every recursive step.

2. **Dedup correctness bug:** `ingester.read_events()` silently defaults to 100 events.
   `append_events()` uses this to load "all" existing events for dedup, but only sees
   the latest 100. Events older than the 100th are invisible to dedup, causing silent
   duplicates and missed supersessions as the store grows.

3. **O(N) ingestion:** Even without the 100-event bug, loading ALL events into memory
   for every `append_events()` call is O(N) and scales poorly.

## Design

### Part 1: Add Missing Indexes

Add to `connection.py` schema (additive DDL, safe for existing DBs):

```sql
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
```

### Part 2: Targeted SQL Dedup

Replace the "load all events, scan in Python" pattern with SQL-targeted lookups.

**Current flow (O(N)):**
```
existing_events = load_all_events()  # O(N)
for candidate in new_events:
    if candidate.id in existing_ids:     # O(1) set lookup but set built from O(N) load
        merge(existing, candidate)
    elif supersession_found(candidate, existing_events):  # O(N) scan
        mark_superseded(...)
    elif duplicate_found(candidate, existing_events):     # O(N) scan
        merge(existing, candidate)
    else:
        append(candidate)
```

**New flow (O(k) per candidate):**
```
for candidate in new_events:
    # Step 1: Exact ID — single PK lookup
    existing = db.get_event_by_id(candidate.id)
    if existing:
        merge(existing, candidate)
        continue

    # Step 2: Supersession — FTS5 pre-filter + negation check
    candidates = db.search_fts(candidate.summary_tokens, limit=20)
    candidates = [c for c in candidates if c.type == candidate.type and c.memory_type == "semantic"]
    for c in candidates:
        if is_contradiction(candidate, c):
            mark_superseded(c, candidate)
            break

    # Step 3: Semantic duplicate — FTS5 pre-filter + Jaccard
    if not superseded:
        candidates = db.search_fts(candidate.summary_tokens, limit=20)
        candidates = [c for c in candidates if c.type == candidate.type]
        best_match = max(candidates, key=lambda c: similarity(candidate, c))
        if above_threshold(best_match):
            merge(best_match, candidate)
            continue

    # Step 4: New event
    append(candidate)
```

**Key changes:**
- `read_events()` call removed from `append_events()` — no full-table load
- Exact ID dedup: `SELECT * FROM events WHERE id = ?` (PK lookup, O(1))
- Semantic dedup: FTS5 `MATCH` narrows to top-20 candidates, Jaccard on those only
- Supersession: same FTS5 narrowing + type/status filter
- Full event loaded only when merge is needed (not for comparison)
- `ensure_event_provenance()` called only on matched events, not all events

### Part 3: What stays the same

- `merge_events()` logic — unchanged
- `event_similarity()` algorithm — unchanged (Jaccard on tokens)
- Supersession negation detection — unchanged
- All threshold values — unchanged
- Event packing/writing — unchanged
- `dedup.py` module — methods still exist, just called with smaller candidate lists

### EventStore additions

Two new query methods on `EventStore`:

```python
def get_event_by_id(self, event_id: str) -> dict[str, Any] | None:
    """Fetch a single event by PK. Returns None if not found."""

def search_fts_by_type(self, query_text: str, event_type: str, k: int = 20) -> list[dict[str, Any]]:
    """FTS5 search filtered by event type."""
```

### Testing strategy

- Contract test: verify indexes exist after schema init
- Unit test: `append_events` with 200+ seeded events finds duplicates beyond the old 100-event window
- Unit test: `append_events` detects supersession in events beyond the 100-event window
- Performance test: `append_events` with 1000 seeded events completes in < 100ms
