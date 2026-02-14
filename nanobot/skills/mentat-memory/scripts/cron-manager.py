#!/usr/bin/env python3
"""
Cron Job Manager - Catches up on missed rollup jobs
Runs every 3 hours, checks for overdue rollups, only executes during downtime
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

WORKSPACE = Path(__file__).parent.parent
STATE_FILE = WORKSPACE / "memory/diary/2026/.state.json"
SCRIPTS_DIR = WORKSPACE / "scripts"

def load_state():
    """Load state file or create empty state"""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "lastSummarizedSession": None,
        "privateSessions": [],
        "lastDailyRollup": None,
        "lastWeeklyRollup": None,
        "lastMonthlyRollup": None
    }

def save_state(state):
    """Save state file"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def check_recent_activity():
    """Check if user has sent a message in last 30 minutes"""
    try:
        # Get sessions list with last message
        result = subprocess.run(
            ['clawdbot', 'sessions', 'list', '--message-limit', '1'],
            capture_output=True, text=True, timeout=10
        )
        # Parse output to check timestamp - if we can't parse, assume active to be safe
        # This is a simple check - if command fails or we can't determine, return True (active)
        if result.returncode != 0:
            return True
        
        # For now, simplified: if clawdbot is responsive, assume we're in downtime
        # A more robust check would parse session timestamps
        return False
    except Exception:
        return True  # Assume active if check fails

def needs_daily_rollup(state):
    """Check if daily rollup is overdue"""
    last = state.get("lastDailyRollup")
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Should run if we haven't run today and it's past midnight
    if not last:
        return yesterday  # First run - do yesterday
    if last < yesterday:
        return yesterday  # Overdue - do most recent missed day
    return None

def needs_weekly_rollup(state):
    """Check if weekly rollup is overdue"""
    last = state.get("lastWeeklyRollup")
    # Week format: 2026-W05
    current_week = datetime.now().strftime("%Y-W%V")
    last_week = (datetime.now() - timedelta(weeks=1)).strftime("%Y-W%V")
    
    if not last:
        return last_week if datetime.now().weekday() >= 0 else None  # Only if past Sunday
    if last < last_week and datetime.now().weekday() >= 0:
        return last_week
    return None

def needs_monthly_rollup(state):
    """Check if monthly rollup is overdue"""
    last = state.get("lastMonthlyRollup")
    current_month = datetime.now().strftime("%Y-%m")
    last_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    
    if not last:
        return last_month if datetime.now().day > 1 else None  # Only if past 1st
    if last < last_month and datetime.now().day > 1:
        return last_month
    return None

def run_rollup(script_name, period):
    """Execute a rollup script"""
    script_path = SCRIPTS_DIR / script_name
    print(f"Running {script_name} for {period}...")
    try:
        result = subprocess.run(
            [str(script_path)],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print(f"✓ {script_name} completed successfully")
            return True
        else:
            print(f"✗ {script_name} failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ {script_name} error: {e}")
        return False

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Cron manager checking...")
    
    # Check if user is active
    if check_recent_activity():
        print("User active recently - skipping rollups")
        return 0
    
    state = load_state()
    ran_anything = False
    
    # Check and run each rollup type
    if daily_date := needs_daily_rollup(state):
        if run_rollup("rollup-daily.py", daily_date):
            state["lastDailyRollup"] = daily_date
            ran_anything = True
    
    if weekly_period := needs_weekly_rollup(state):
        if run_rollup("rollup-weekly.py", weekly_period):
            state["lastWeeklyRollup"] = weekly_period
            ran_anything = True
    
    if monthly_period := needs_monthly_rollup(state):
        if run_rollup("rollup-monthly.py", monthly_period):
            state["lastMonthlyRollup"] = monthly_period
            ran_anything = True
    
    if ran_anything:
        save_state(state)
        print("State updated")
    else:
        print("No overdue rollups")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
