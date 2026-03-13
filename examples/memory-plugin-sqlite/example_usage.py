"""Example usage of SQLite memory provider.

This example demonstrates how to use the SQLite memory provider
both programmatically and via configuration.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path


def demo_basic_usage():
    """Demonstrate basic CRUD operations."""
    print("=" * 60)
    print("SQLite Memory Provider - Basic Usage Demo")
    print("=" * 60)
    
    from sqlite_memory_provider import SQLiteMemoryProvider
    
    # Create provider with temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    provider = SQLiteMemoryProvider({"db_path": db_path})
    print(f"\n1. Created SQLite provider")
    print(f"   Database: {db_path}")
    print(f"   FTS5 enabled: {provider._use_fts5}")
    
    # Write long-term memory
    print("\n2. Writing long-term memory...")
    provider.write_long_term("""# User Information

## Personal
- Name: Alice
- Location: Shanghai

## Preferences
- Theme: Dark mode
- Language: Chinese

## Projects
- Working on: nanobot memory plugin
""")
    
    # Read it back
    content = provider.read_long_term()
    print(f"   Stored {len(content)} characters")
    
    # Append history entries
    print("\n3. Appending history entries...")
    entries = [
        "[2024-01-15 09:00] Started working on SQLite provider",
        "[2024-01-15 10:30] Implemented basic CRUD operations",
        "[2024-01-15 14:00] Added FTS5 full-text search support",
        "[2024-01-15 16:45] Testing and debugging",
    ]
    for entry in entries:
        provider.append_history(entry)
    print(f"   Added {len(entries)} history entries")
    
    # Search history
    print("\n4. Searching history...")
    results = provider.search_history(query="FTS5")
    print(f"   Found {len(results)} entries matching 'FTS5':")
    for r in results:
        print(f"     - {r.content[:50]}...")
    
    # Get stats
    print("\n5. Memory statistics:")
    stats = provider.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    # Cleanup
    provider.close()
    Path(db_path).unlink(missing_ok=True)
    print("\n✓ Demo completed!")


def demo_time_based_search():
    """Demonstrate time-based search."""
    print("\n" + "=" * 60)
    print("SQLite Memory Provider - Time-based Search Demo")
    print("=" * 60)
    
    from sqlite_memory_provider import SQLiteMemoryProvider
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    provider = SQLiteMemoryProvider({"db_path": db_path})
    
    # Add entries with different timestamps
    base_time = datetime(2024, 1, 15, 12, 0)
    
    print("\n1. Adding entries at different times...")
    for i in range(5):
        timestamp = base_time + timedelta(hours=i)
        entry = f"[{timestamp.strftime('%Y-%m-%d %H:%M')}] Activity {i+1}"
        provider.append_history(entry)
    print("   Added 5 entries over 5 hours")
    
    # Search by time range
    print("\n2. Searching entries from 13:00 to 15:00...")
    start = base_time + timedelta(hours=1)
    end = base_time + timedelta(hours=3)
    results = provider.search_history(start_time=start, end_time=end)
    print(f"   Found {len(results)} entries:")
    for r in results:
        print(f"     - {r.content}")
    
    # Cleanup
    provider.close()
    Path(db_path).unlink(missing_ok=True)
    print("\n✓ Demo completed!")


def demo_with_nanobot_config():
    """Demonstrate configuration for nanobot."""
    print("\n" + "=" * 60)
    print("SQLite Memory Provider - Nanobot Configuration")
    print("=" * 60)
    
    print("""
To use SQLite memory provider with nanobot, add to your config.yaml:

```yaml
memory:
  provider: "sqlite"
  config:
    db_path: "~/.nanobot/memory.db"
    use_fts5: true  # Enable full-text search (recommended)
```

Or programmatically:

```python
from nanobot.memory import create_memory_provider

provider = create_memory_provider("sqlite", {
    "db_path": "~/.nanobot/memory.db",
    "use_fts5": True
})
```

The provider will automatically:
1. Create the database file if it doesn't exist
2. Initialize the schema (long_term and history tables)
3. Set up FTS5 for full-text search (if available)

Benefits over filesystem provider:
- ACID guarantees for data integrity
- Efficient full-text search
- Structured storage with metadata
- Easy backup (single file)
- Concurrent access support
""")


def demo_custom_provider_registration():
    """Demonstrate custom provider registration."""
    print("\n" + "=" * 60)
    print("SQLite Memory Provider - Custom Registration")
    print("=" * 60)
    
    from nanobot.memory import MemoryProviderRegistry, create_memory_provider
    
    # Import to register the provider
    import sqlite_memory_provider  # noqa: F401
    
    print("\n1. Checking registered providers...")
    providers = MemoryProviderRegistry.list_providers()
    print(f"   Available: {providers}")
    
    if "sqlite" in providers:
        print("\n2. Creating provider via registry...")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        provider = create_memory_provider("sqlite", {"db_path": db_path})
        print(f"   Created: {provider.name}")
        print(f"   Available: {provider.is_available}")
        
        provider.close()
        Path(db_path).unlink(missing_ok=True)
    
    print("\n✓ Provider registered successfully!")


def demo_migration_from_filesystem():
    """Demonstrate migrating from filesystem provider."""
    print("\n" + "=" * 60)
    print("SQLite Memory Provider - Migration from Filesystem")
    print("=" * 60)
    
    import tempfile
    from pathlib import Path
    from nanobot.memory import FilesystemMemoryProvider
    from sqlite_memory_provider import SQLiteMemoryProvider
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create filesystem provider and add some data
        print("\n1. Creating filesystem provider with sample data...")
        fs_provider = FilesystemMemoryProvider({"workspace": tmpdir})
        fs_provider.write_long_term("# User Info\n\nName: Bob")
        fs_provider.append_history("[2024-01-15 10:00] First entry")
        fs_provider.append_history("[2024-01-15 11:00] Second entry")
        
        # Read from filesystem
        long_term = fs_provider.read_long_term()
        print(f"   Long-term: {long_term[:30]}...")
        
        # Create SQLite provider
        db_path = Path(tmpdir) / "memory.db"
        print("\n2. Creating SQLite provider...")
        sqlite_provider = SQLiteMemoryProvider({"db_path": str(db_path)})
        
        # Migrate data
        print("\n3. Migrating data...")
        sqlite_provider.write_long_term(long_term)
        
        # Read history from filesystem and migrate
        history_entries = fs_provider.search_history(limit=1000)
        for entry in reversed(history_entries):  # Reverse to maintain order
            sqlite_provider.append_history(entry.content)
        
        print(f"   Migrated {len(history_entries)} history entries")
        
        # Verify
        print("\n4. Verifying migration...")
        migrated_long_term = sqlite_provider.read_long_term()
        migrated_history = sqlite_provider.search_history(limit=1000)
        print(f"   Long-term matches: {migrated_long_term == long_term}")
        print(f"   History count: {len(migrated_history)}")
        
        sqlite_provider.close()
    
    print("\n✓ Migration demo completed!")


if __name__ == "__main__":
    # Run all demos
    demo_basic_usage()
    demo_time_based_search()
    demo_with_nanobot_config()
    demo_custom_provider_registration()
    demo_migration_from_filesystem()
    
    print("\n" + "=" * 60)
    print("All demos completed successfully!")
    print("=" * 60)
