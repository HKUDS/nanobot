#!/usr/bin/env python3
"""
Session Summarization Script
Called at session start to check if previous session needs summarization
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Workspace root
WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"
STATE_FILE = DIARY_ROOT / "2026" / ".state.json"


def load_state():
    """Load current state"""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"lastSummarizedSession": None}


def save_state(state):
    """Save state"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_current_session_key():
    """Get current session key from environment or stdin"""
    # This would be passed via Clawdbot context
    # For now, return placeholder
    return os.environ.get("CLAWDBOT_SESSION_KEY", "unknown")


def needs_summarization(state, current_session):
    """Check if previous session needs summarization"""
    last = state.get("lastSummarizedSession")
    if last is None:
        return False  # First session
    return last != current_session


def main():
    state = load_state()
    current_session = get_current_session_key()
    
    if needs_summarization(state, current_session):
        # Signal to Clawdbot that summarization is needed
        print("SUMMARIZE_NEEDED")
        print(f"Last: {state['lastSummarizedSession']}")
        print(f"Current: {current_session}")
    else:
        print("SUMMARIZE_SKIP")
    
    # Update state
    state["lastSummarizedSession"] = current_session
    save_state(state)


if __name__ == "__main__":
    main()
