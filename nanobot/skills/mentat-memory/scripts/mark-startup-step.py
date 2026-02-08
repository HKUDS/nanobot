#!/usr/bin/env python3
"""
Mark a startup step as completed.

Usage:
    python3 scripts/mark-startup-step.py soul
    python3 scripts/mark-startup-step.py user
    python3 scripts/mark-startup-step.py memory
"""

import sys
import json
from pathlib import Path
from datetime import datetime

STATE_FILE = Path(".startup-state.json")

STEP_MAP = {
    "soul": "soul_loaded",
    "user": "user_loaded",
    "memory": "memory_loaded",
    "diary": "diary_loaded"
}

def update_startup_state(key, value=True):
    """Update a specific step in the startup state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
    else:
        print("Error: No startup state file found!", file=sys.stderr)
        sys.exit(1)
    
    state[key] = value
    state["timestamp"] = datetime.now().isoformat()
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: mark-startup-step.py <step>", file=sys.stderr)
        print(f"Valid steps: {', '.join(STEP_MAP.keys())}", file=sys.stderr)
        sys.exit(1)
    
    step_name = sys.argv[1].lower()
    
    if step_name not in STEP_MAP:
        print(f"Error: Unknown step '{step_name}'", file=sys.stderr)
        print(f"Valid steps: {', '.join(STEP_MAP.keys())}", file=sys.stderr)
        sys.exit(1)
    
    update_startup_state(STEP_MAP[step_name], True)
    print(f"✓ Marked {step_name} as loaded")
