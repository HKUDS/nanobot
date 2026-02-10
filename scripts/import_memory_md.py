#!/usr/bin/env python3
"""
Import existing MEMORY.md and daily notes into vector memory (Mem0 + ChromaDB).

Usage:
    python scripts/import_memory_md.py [--workspace ~/.nanobot/workspace] [--user-id global] [--dry-run]

This script reads the existing file-based memories and imports them into the
vector memory store. It's meant to be run once during migration from the
file-based memory system to the vector-based one.
"""

import argparse
import sys
from pathlib import Path

# Ensure nanobot package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Import MEMORY.md and daily notes into vector memory."
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="~/.nanobot/workspace",
        help="Path to the nanobot workspace (default: ~/.nanobot/workspace)",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="User ID namespace for imported memories (default: None = global)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without actually importing",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of daily notes to import (default: 30)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    memory_dir = workspace / "memory"

    if not memory_dir.exists():
        print(f"Error: Memory directory not found at {memory_dir}")
        sys.exit(1)

    print(f"Workspace: {workspace}")
    print(f"Memory dir: {memory_dir}")
    print(f"User ID: {args.user_id or '(global)'}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Collect content to import
    chunks_to_import = []

    # 1. Import MEMORY.md
    memory_file = memory_dir / "MEMORY.md"
    if memory_file.exists():
        content = memory_file.read_text(encoding="utf-8")
        if content.strip():
            chunks_to_import.append(("MEMORY.md", content))
            print(f"Found MEMORY.md ({len(content)} chars)")
    else:
        print("No MEMORY.md found")

    # 2. Import daily notes
    daily_files = sorted(memory_dir.glob("????-??-??.md"), reverse=True)
    imported_days = 0
    for daily_file in daily_files:
        if imported_days >= args.days:
            break
        content = daily_file.read_text(encoding="utf-8")
        if content.strip():
            chunks_to_import.append((daily_file.name, content))
            print(f"Found {daily_file.name} ({len(content)} chars)")
            imported_days += 1

    if not chunks_to_import:
        print("\nNo content to import.")
        sys.exit(0)

    print(f"\nTotal files to import: {len(chunks_to_import)}")

    if args.dry_run:
        print("\n--- DRY RUN: showing chunks that would be imported ---")
        for name, content in chunks_to_import:
            preview = content[:200].replace("\n", " ")
            print(f"\n[{name}] {preview}...")
        print("\nDone (dry run). No data was imported.")
        sys.exit(0)

    # Actually import
    print("\nInitializing vector memory store...")

    from nanobot.config.schema import MemoryConfig
    from nanobot.memory.vector_store import VectorMemoryStore

    config = MemoryConfig(backend="vector")
    store = VectorMemoryStore(workspace, config)

    total_imported = 0
    for name, content in chunks_to_import:
        print(f"Importing {name}...", end=" ")
        source = "import_memory_md" if name == "MEMORY.md" else "import_daily_note"
        count = store.import_from_text(
            content,
            user_id=args.user_id,
            source=source,
        )
        total_imported += count
        print(f"{count} memories extracted")

    print(f"\nDone! Total memories imported: {total_imported}")

    # Show what was imported
    print("\n--- Imported memories ---")
    all_mems = store.get_all(user_id=args.user_id, limit=50)
    for i, mem in enumerate(all_mems, 1):
        print(f"  {i}. {mem.text[:100]}...")


if __name__ == "__main__":
    main()
