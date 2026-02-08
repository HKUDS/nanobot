#!/usr/bin/env python3
"""
Sandman Orchestrator - Triggers Deva to run overnight analysis tasks
This script is called by cron and sends a message to Deva to execute Sandman tasks.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path('/home/deva/shared')
STATE_FILE = WORKSPACE / 'memory/.sandman-state.json'
SANDMAN_NIGHTLY_BUDGET = 5.00

def load_state():
    """Load sandman state from previous runs."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        'last_run': None,
        'completed_tasks': [],
        'total_spent': 0,
        'sandman_daily_spend': 0.0,
        'last_budget_reset': None
    }

def save_state(state):
    """Save sandman state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def main():
    """Trigger Deva to run Sandman tasks."""
    state = load_state()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Reset daily spend if it's a new day
    if state.get('last_budget_reset') != today:
        state['sandman_daily_spend'] = 0.0
        state['last_budget_reset'] = today
        save_state(state)
    
    sandman_spent_today = state.get('sandman_daily_spend', 0.0)
    remaining = SANDMAN_NIGHTLY_BUDGET - sandman_spent_today
    
    print(f"🌙 Sandman Orchestrator")
    print(f"Spent today: ${sandman_spent_today:.2f}")
    print(f"Remaining: ${remaining:.2f}")
    
    if remaining <= 0:
        print("⚠️  Budget exhausted. Skipping.")
        return 0
    
    # Write trigger file for Deva to find
    trigger_file = WORKSPACE / '.sandman-trigger.json'
    trigger_data = {
        'timestamp': datetime.now().isoformat(),
        'budget_remaining': remaining,
        'date': today
    }
    
    with open(trigger_file, 'w') as f:
        json.dump(trigger_data, f, indent=2)
    
    print(f"✅ Trigger file created: {trigger_file}")
    print("Deva will execute tasks via sessions_spawn tool")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
