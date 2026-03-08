#!/usr/bin/env python3
"""
Test memory extraction with sample daily logs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from memory_extraction import extract_atomic_memories, generate_narrative_summary

# Test samples
SAMPLES = [
    {
        "name": "Bug Report",
        "content": """# 2026-01-28

## Sessions

### Session Test
User reported critical bug in payment processing. Severity: High.
Dashboard loading very slow (5+ seconds). This is a major performance issue.
Made decision to use Python for backend rewrite instead of Node.js.
"""
    },
    {
        "name": "Preferences",
        "content": """# 2026-01-28

## Sessions

### Session Preferences
User mentioned they prefer email notifications over SMS.
User likes working in the morning (9am-12pm).
User prefers direct communication style, no fluff.
"""
    },
    {
        "name": "Technical Work",
        "content": """# 2026-01-28

## Events
- Fixed Redis connection errors by restarting service
- Deployed new dashboard to staging
- Started database migration planning
- Reviewed security audit results

## Notes
Redis restart is becoming a pattern - need to investigate root cause.
"""
    },
    {
        "name": "Mixed Content",
        "content": """# 2026-01-28

## Sessions

### Morning Chat
User said hello. Discussed weather. User mentioned they're traveling next week.
Important: User's presentation deadline is Friday, Feb 3rd. High stakes.

### Afternoon Work
Completed dashboard optimization work. Performance improved from 5s to 1.2s load time.
User very happy with results - praised the work. 

## Notes
Need to follow up on travel arrangements before next week.
"""
    }
]


def run_tests():
    """Run extraction tests on all samples."""
    print("=" * 60)
    print("MEMORY EXTRACTION TEST SUITE")
    print("=" * 60)
    print()
    
    for i, sample in enumerate(SAMPLES, 1):
        print(f"Test {i}: {sample['name']}")
        print("-" * 60)
        
        memories = extract_atomic_memories(sample['content'])
        
        if not memories:
            print("⚠️ No memories extracted (all below importance threshold)")
        else:
            print(f"✅ Extracted {len(memories)} memories:\n")
            
            for j, mem in enumerate(memories, 1):
                print(f"  {j}. [{mem['importance']}/10] {mem['content']}")
                print(f"     Category: {mem['category']}")
                print(f"     Tags: {mem['tags']}")
                print()
            
            # Test narrative generation
            print("Narrative Summary:")
            narrative = generate_narrative_summary(memories)
            print(f"  {narrative}")
        
        print()
        print("=" * 60)
        print()


if __name__ == "__main__":
    run_tests()
