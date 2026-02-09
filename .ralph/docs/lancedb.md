# LanceDB Reference

LanceDB is an embedded vector database. No server required.

## Installation

```bash
pip install lancedb
```

## Basic Usage

```python
import lancedb

# Connect to a local database (creates if doesn't exist)
db = lancedb.connect("~/.nanobot/memory.lance")

# Create a table with data
data = [
    {"id": "1", "content": "hello world", "embedding": [0.1, 0.2, 0.3, ...]},
    {"id": "2", "content": "goodbye", "embedding": [0.4, 0.5, 0.6, ...]},
]
table = db.create_table("turns", data)

# Or open existing table
table = db.open_table("turns")

# Add more data
table.add([
    {"id": "3", "content": "new message", "embedding": [0.7, 0.8, 0.9, ...]}
])
```

## Vector Search

```python
# Search by embedding vector
query_embedding = [0.1, 0.2, 0.3, ...]
results = table.search(query_embedding).limit(10).to_list()

# Results are dicts with _distance field
for r in results:
    print(f"ID: {r['id']}, Distance: {r['_distance']}")
```

## Filtering

```python
# Filter with SQL-like where clause
results = (
    table.search(query_embedding)
    .where("channel = 'telegram'")
    .limit(5)
    .to_list()
)

# Multiple conditions
results = (
    table.search(query_embedding)
    .where("timestamp > 1700000000 AND role = 'user'")
    .limit(10)
    .to_list()
)
```

## Schema with PyArrow

```python
import pyarrow as pa

schema = pa.schema([
    pa.field("id", pa.string()),
    pa.field("content", pa.string()),
    pa.field("role", pa.string()),
    pa.field("channel", pa.string()),
    pa.field("timestamp", pa.float64()),
    pa.field("prev_turn_id", pa.string()),
    pa.field("next_turn_id", pa.string()),
    pa.field("embedding", pa.list_(pa.float32(), 384)),  # 384 for all-MiniLM-L6-v2
])

# Create empty table with schema
table = db.create_table("turns", schema=schema)
```

## Updating Records

```python
# Update requires knowing the row IDs
# Typically: delete + add for simplicity

# Or use merge for upsert-like behavior
table.merge(
    new_data,
    left_on="id",
    right_on="id",
)
```

## Deleting Records

```python
# Delete with filter
table.delete("id = '123'")

# Delete multiple
table.delete("timestamp < 1700000000")
```

## Async API

```python
import lancedb

# Async connection
db = await lancedb.connect_async("~/.nanobot/memory.lance")

# Async table operations
table = await db.open_table("turns")
results = await table.search(query_embedding).limit(10).to_list()
```

## Best Practices

1. **Use consistent embedding dimensions** — all-MiniLM-L6-v2 produces 384-dim vectors
2. **Index large tables** — create ANN index for tables >100k rows
3. **Batch inserts** — add data in batches for better performance
4. **Use where clauses** — filter before vector search when possible

## Creating an Index (for large tables)

```python
# Create IVF-PQ index for faster search
table.create_index(
    metric="L2",
    num_partitions=256,
    num_sub_vectors=96,
)
```
