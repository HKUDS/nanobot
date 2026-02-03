#!/usr/bin/env python3
"""
Memory system health dashboard and analytics.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_config import MEMORY_CONFIG


def generate_dashboard(memory_bank_path: Path):
    """
    Generate memory system health dashboard.
    """
    if not memory_bank_path.exists():
        print("=" * 60)
        print("MEMORY SYSTEM DASHBOARD")
        print("=" * 60)
        print("No memory bank found. Run rollup-daily.py to start building memories.")
        print("=" * 60)
        return
    
    memories = []
    with open(memory_bank_path, "r") as f:
        for line in f:
            try:
                memories.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    total = len(memories)
    active = sum(1 for m in memories if m.get("status") == "active")
    archived = sum(1 for m in memories if m.get("status") == "archived")
    superseded = sum(1 for m in memories if m.get("status") == "superseded")
    
    # Category breakdown
    categories = Counter(m.get("category", "unknown") for m in memories if m.get("status") == "active")
    
    # Importance distribution
    importance_dist = Counter(m.get("importance", 0) for m in memories if m.get("status") == "active")
    
    # Recent activity (last 7 days)
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    recent = []
    for m in memories:
        try:
            mem_time = datetime.fromisoformat(m["timestamp"])
            if mem_time.tzinfo:
                week_ago_aware = week_ago.replace(tzinfo=mem_time.tzinfo)
            else:
                week_ago_aware = week_ago
            
            if mem_time >= week_ago_aware:
                recent.append(m)
        except (KeyError, ValueError):
            continue
    
    # Top accessed
    top_accessed = sorted(
        [m for m in memories if m.get("status") == "active"],
        key=lambda m: m.get("access_count", 0),
        reverse=True
    )[:5]
    
    # Top domains
    domain_counts = Counter()
    for m in memories:
        if m.get("status") == "active":
            domains = m.get("tags", {}).get("domain", [])
            if isinstance(domains, list):
                domain_counts.update(domains)
    
    # Print dashboard
    print("=" * 60)
    print("MEMORY SYSTEM DASHBOARD")
    print("=" * 60)
    print(f"Total Memories: {total}")
    print(f"  Active: {active}")
    print(f"  Archived: {archived}")
    print(f"  Superseded: {superseded}")
    print()
    
    print("Category Breakdown:")
    for cat, count in categories.most_common():
        bar = "█" * count
        print(f"  {cat:12} {bar} ({count})")
    print()
    
    print("Importance Distribution:")
    for imp in range(10, 0, -1):
        count = importance_dist.get(imp, 0)
        if count > 0:
            bar = "█" * count
            print(f"  {imp:2}/10: {bar} ({count})")
    print()
    
    print(f"Recent Activity (Last 7 Days): {len(recent)} memories")
    avg_per_day = len(recent) / 7.0
    print(f"  Average per day: {avg_per_day:.1f}")
    print()
    
    print("Top Domains:")
    for domain, count in domain_counts.most_common(5):
        print(f"  {domain:12} ({count})")
    print()
    
    if top_accessed and top_accessed[0].get("access_count", 0) > 0:
        print("Top Accessed Memories:")
        for i, mem in enumerate(top_accessed, 1):
            if mem.get("access_count", 0) > 0:
                print(f"  {i}. [{mem['access_count']} accesses] {mem['content'][:60]}...")
    else:
        print("Top Accessed Memories: (none accessed yet)")
    print()
    
    # Feature flag status
    print("Feature Flags:")
    print(f"  Structured Extraction: {'✅ ENABLED' if MEMORY_CONFIG['ENABLE_STRUCTURED_EXTRACTION'] else '❌ DISABLED'}")
    print(f"  Consolidation:         {'✅ ENABLED' if MEMORY_CONFIG['ENABLE_CONSOLIDATION'] else '❌ DISABLED'}")
    print(f"  Weighted Retrieval:    {'✅ ENABLED' if MEMORY_CONFIG['ENABLE_WEIGHTED_RETRIEVAL'] else '❌ DISABLED'}")
    print(f"  Embeddings:            {'✅ ENABLED' if MEMORY_CONFIG['ENABLE_EMBEDDINGS'] else '❌ DISABLED'}")
    print(f"  Memory Decay:          {'✅ ENABLED' if MEMORY_CONFIG['ENABLE_DECAY'] else '❌ DISABLED'}")
    print()
    
    print("=" * 60)


def show_recent_memories(memory_bank_path: Path, days: int = 3, limit: int = 10):
    """Show most recent memories."""
    if not memory_bank_path.exists():
        print("No memory bank found.")
        return
    
    memories = []
    with open(memory_bank_path, "r") as f:
        for line in f:
            try:
                memories.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    # Filter to active and recent
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    
    recent = []
    for m in memories:
        if m.get("status") != "active":
            continue
        try:
            mem_time = datetime.fromisoformat(m["timestamp"])
            if mem_time.tzinfo:
                cutoff_aware = cutoff.replace(tzinfo=mem_time.tzinfo)
            else:
                cutoff_aware = cutoff
            
            if mem_time >= cutoff_aware:
                recent.append(m)
        except (KeyError, ValueError):
            continue
    
    # Sort by timestamp (newest first)
    recent.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
    
    print(f"Recent Memories (Last {days} Days):")
    print("=" * 60)
    
    for i, mem in enumerate(recent[:limit], 1):
        print(f"{i}. [{mem.get('importance', 0)}/10] {mem['content']}")
        print(f"   Category: {mem.get('category', 'unknown')}")
        print(f"   Tags: {mem.get('tags', {})}")
        print(f"   Time: {mem.get('timestamp', 'N/A')}")
        print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Memory system dashboard")
    parser.add_argument("--bank", default="memory/diary/2026/memories.jsonl", help="Memory bank path")
    parser.add_argument("--recent", action="store_true", help="Show recent memories instead")
    parser.add_argument("--days", type=int, default=3, help="Days to look back (with --recent)")
    parser.add_argument("--limit", type=int, default=10, help="Max memories to show (with --recent)")
    
    args = parser.parse_args()
    
    memory_bank = Path(args.bank)
    
    if args.recent:
        show_recent_memories(memory_bank, days=args.days, limit=args.limit)
    else:
        generate_dashboard(memory_bank)
