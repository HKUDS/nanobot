# SQLite Memory Provider for nanobot

A production-ready memory provider that stores nanobot's memory in SQLite database.

## Features

- **Persistent Storage**: ACID-compliant data persistence
- **Full-Text Search**: Optional FTS5 support for fast history searching
- **Structured Storage**: Metadata support for advanced filtering
- **Easy Backup**: Single-file database for simple backup/restore
- **Concurrent Access**: SQLite handles concurrent reads safely

## Installation

No additional dependencies required - uses Python's built-in `sqlite3` module.

## Usage

### Configuration File

Add to your `~/.nanobot/config.yaml`:

```yaml
memory:
  provider: "sqlite"
  config:
    db_path: "~/.nanobot/memory.db"
    use_fts5: true  # Enable full-text search (recommended)
```

### Programmatic Usage

```python
from nanobot.memory import create_memory_provider

# Create provider
provider = create_memory_provider("sqlite", {
    "db_path": "~/.nanobot/memory.db",
    "use_fts5": True
})

# Use like any memory provider
provider.write_long_term("# User Info\n\nName: Alice")
provider.append_history("[2024-01-15 10:30] Started new project")

# Search with full-text search
results = provider.search_history(query="project")
```

### Custom Registration

```python
from nanobot.memory import MemoryProviderRegistry
from sqlite_memory_provider import SQLiteMemoryProvider

# Register (if not auto-imported)
MemoryProviderRegistry.register("sqlite", SQLiteMemoryProvider)

# Create instance
provider = MemoryProviderRegistry.create_provider("sqlite", {
    "db_path": "/path/to/memory.db"
})
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `db_path` | str | `~/.nanobot/memory.db` | Path to SQLite database file |
| `use_fts5` | bool | `true` | Enable FTS5 full-text search (auto-disabled if not available) |

## Database Schema

### long_term Table
```sql
CREATE TABLE long_term (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### history Table
```sql
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON-encoded
);
```

### history_fts Table (FTS5 virtual table, optional)
```sql
CREATE VIRTUAL TABLE history_fts USING fts5(
    content,
    content_rowid=rowid,
    content=history
);
```

## Migration from Filesystem Provider

To migrate existing memory from filesystem to SQLite:

```python
from nanobot.memory import FilesystemMemoryProvider
from sqlite_memory_provider import SQLiteMemoryProvider

# Load from filesystem
fs = FilesystemMemoryProvider({"workspace": "/path/to/workspace"})
long_term = fs.read_long_term()
history = fs.search_history(limit=10000)

# Save to SQLite
sqlite = SQLiteMemoryProvider({"db_path": "/path/to/memory.db"})
sqlite.write_long_term(long_term)
for entry in reversed(history):
    sqlite.append_history(entry.content)
```

## Running the Example

```bash
cd examples/memory-plugin-sqlite
python example_usage.py
```

This will run several demos showing:
- Basic CRUD operations
- Time-based search
- Configuration examples
- Migration from filesystem

## Benefits vs Filesystem Provider

| Feature | Filesystem | SQLite |
|---------|------------|--------|
| ACID Compliance | ❌ | ✅ |
| Full-Text Search | ❌ (grep only) | ✅ (FTS5) |
| Structured Metadata | ❌ | ✅ |
| Concurrent Access | ⚠️ (file locking) | ✅ |
| Backup | Multiple files | Single file |
| Query Performance | O(n) | O(log n) or O(1) with FTS |

## Troubleshooting

### FTS5 Not Available
If you see `FTS5 disabled`, your SQLite was compiled without FTS5 support. The provider will automatically fall back to LIKE-based search.

To check FTS5 availability:
```python
import sqlite3
conn = sqlite3.connect(":memory:")
try:
    conn.execute("CREATE VIRTUAL TABLE test USING fts5(content)")
    print("FTS5 available")
except sqlite3.OperationalError:
    print("FTS5 not available")
```

### Database Locked
If you encounter "database is locked" errors:
- Ensure no other process is writing to the database
- Check that previous connections were properly closed
- Consider using WAL mode for better concurrency

## License

Same as nanobot project.
