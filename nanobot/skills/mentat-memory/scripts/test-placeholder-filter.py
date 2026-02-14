#!/usr/bin/env python3
"""
Test script to demonstrate placeholder session filtering.
Creates mock session data and shows what would be filtered.
"""
import json
from datetime import datetime, timedelta

def create_mock_sessions():
    """Create example sessions showing what gets filtered."""
    sessions = [
        {
            "id": "placeholder-1",
            "duration_minutes": 0.5,
            "user_messages": 0,
            "description": "Short session, no user messages - FILTERED"
        },
        {
            "id": "placeholder-2", 
            "duration_minutes": 1.8,
            "user_messages": 0,
            "description": "Under 2 min, no user messages - FILTERED"
        },
        {
            "id": "normal-1",
            "duration_minutes": 0.5,
            "user_messages": 1,
            "description": "Short but has user message - KEPT"
        },
        {
            "id": "normal-2",
            "duration_minutes": 5.0,
            "user_messages": 0,
            "description": "Long duration (over 2 min) - KEPT"
        },
        {
            "id": "normal-3",
            "duration_minutes": 15.0,
            "user_messages": 5,
            "description": "Normal conversation - KEPT"
        },
    ]
    return sessions

def is_placeholder(session):
    """Check if session is a placeholder (matches load-context.py logic)."""
    return session["duration_minutes"] < 2 and session["user_messages"] == 0

def main():
    sessions = create_mock_sessions()
    
    print("=== PLACEHOLDER SESSION FILTERING TEST ===\n")
    print("Filter criteria: duration < 2 minutes AND user_messages = 0\n")
    
    placeholders = [s for s in sessions if is_placeholder(s)]
    normal = [s for s in sessions if not is_placeholder(s)]
    
    print("FILTERED OUT (Placeholders):")
    for s in placeholders:
        print(f"  ❌ {s['id']}: {s['description']}")
        print(f"     Duration: {s['duration_minutes']}min, User msgs: {s['user_messages']}\n")
    
    print("\nKEPT (Normal Sessions):")
    for s in normal:
        print(f"  ✅ {s['id']}: {s['description']}")
        print(f"     Duration: {s['duration_minutes']}min, User msgs: {s['user_messages']}\n")
    
    print("=== SUMMARY ===")
    print(f"Total sessions: {len(sessions)}")
    print(f"Filtered (placeholders): {len(placeholders)} ({len(placeholders)/len(sessions)*100:.0f}%)")
    print(f"Kept (normal): {len(normal)} ({len(normal)/len(sessions)*100:.0f}%)")
    print(f"\nTo include placeholders in load-context.py, use: --include-placeholders")

if __name__ == "__main__":
    main()
