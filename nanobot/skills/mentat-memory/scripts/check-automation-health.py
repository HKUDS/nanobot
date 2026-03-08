#!/usr/bin/env python3
"""
Health check for memory automation system
Verifies that all components are functioning correctly
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"

def check_state_file():
    """Verify .state.json exists and has valid structure"""
    state_file = DIARY_ROOT / "2026" / ".state.json"
    
    if not state_file.exists():
        return {
            "status": "FAIL",
            "message": "State file does not exist"
        }
    
    try:
        with open(state_file) as f:
            state = json.load(f)
        
        required_keys = ["lastSummarizedSession", "privateSessions"]
        missing = [k for k in required_keys if k not in state]
        
        if missing:
            return {
                "status": "WARN",
                "message": f"Missing keys: {missing}"
            }
        
        return {
            "status": "PASS",
            "message": f"Valid state file with {len(state)} keys",
            "data": state
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "message": f"Error reading state file: {e}"
        }

def check_daily_files():
    """Check if daily files exist for recent days"""
    today = datetime.now(ZoneInfo("America/Edmonton"))
    daily_dir = DIARY_ROOT / "2026" / "daily"
    
    if not daily_dir.exists():
        return {
            "status": "FAIL",
            "message": "Daily directory does not exist"
        }
    
    # Check last 7 days
    missing_days = []
    for i in range(7):
        date = today - timedelta(days=i)
        daily_file = daily_dir / f"{date.strftime('%Y-%m-%d')}.md"
        if not daily_file.exists() and date.weekday() < 5:  # Only weekdays
            missing_days.append(date.strftime('%Y-%m-%d'))
    
    if missing_days:
        return {
            "status": "WARN",
            "message": f"Missing daily files: {missing_days}"
        }
    
    return {
        "status": "PASS",
        "message": "Daily files present for last 7 days"
    }

def check_session_summarization():
    """Check if sessions are being summarized"""
    try:
        # Get total sessions
        result = subprocess.run(
            ["clawdbot", "sessions", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "status": "FAIL",
                "message": "Cannot list sessions"
            }
        
        data = json.loads(result.stdout)
        sessions = [s for s in data.get("sessions", []) if "subagent" not in s.get("key", "")]
        total_sessions = len(sessions)
        
        # Count summaries in today's file
        today = datetime.now(ZoneInfo("America/Edmonton"))
        daily_file = DIARY_ROOT / "2026" / "daily" / f"{today.strftime('%Y-%m-%d')}.md"
        
        if daily_file.exists():
            content = daily_file.read_text()
            summarized_sessions = content.count("### Session")
        else:
            summarized_sessions = 0
        
        if total_sessions > 0:
            rate = (summarized_sessions / total_sessions) * 100
            
            if rate < 50:
                return {
                    "status": "WARN",
                    "message": f"Low summarization rate: {summarized_sessions}/{total_sessions} ({rate:.0f}%)"
                }
            
            return {
                "status": "PASS",
                "message": f"Summarization rate: {summarized_sessions}/{total_sessions} ({rate:.0f}%)"
            }
        
        return {
            "status": "INFO",
            "message": "No sessions to check yet"
        }
        
    except Exception as e:
        return {
            "status": "FAIL",
            "message": f"Error checking sessions: {e}"
        }

def check_rollup_timestamps():
    """Check when rollups last ran"""
    state_file = DIARY_ROOT / "2026" / ".state.json"
    
    if not state_file.exists():
        return {
            "status": "WARN",
            "message": "No state file to check rollup timestamps"
        }
    
    try:
        with open(state_file) as f:
            state = json.load(f)
        
        now = datetime.now(ZoneInfo("America/Edmonton")).timestamp()
        daily_ts = state.get("lastDailyRollup")
        weekly_ts = state.get("lastWeeklyRollup")
        monthly_ts = state.get("lastMonthlyRollup")
        
        results = []
        
        # Check daily (should run within last 24h)
        if daily_ts:
            age = (now - daily_ts) / 3600
            if age > 24:
                results.append(f"Daily rollup overdue ({age:.1f}h ago)")
        else:
            results.append("Daily rollup never run")
        
        # Check weekly (should run within last 7 days if it's past Sunday)
        if datetime.now(ZoneInfo("America/Edmonton")).weekday() >= 0:  # Monday or later
            if weekly_ts:
                age = (now - weekly_ts) / 86400
                if age > 7:
                    results.append(f"Weekly rollup overdue ({age:.1f}d ago)")
            else:
                results.append("Weekly rollup never run")
        
        if results:
            return {
                "status": "WARN",
                "message": "; ".join(results)
            }
        
        return {
            "status": "PASS",
            "message": "Rollups running on schedule"
        }
        
    except Exception as e:
        return {
            "status": "FAIL",
            "message": f"Error checking rollup timestamps: {e}"
        }

def check_memory_md():
    """Check if MEMORY.md exists and has content"""
    memory_file = WORKSPACE / "MEMORY.md"
    
    if not memory_file.exists():
        return {
            "status": "FAIL",
            "message": "MEMORY.md does not exist"
        }
    
    content = memory_file.read_text()
    
    if len(content) < 100:
        return {
            "status": "WARN",
            "message": f"MEMORY.md exists but is very short ({len(content)} chars)"
        }
    
    return {
        "status": "PASS",
        "message": f"MEMORY.md exists ({len(content)} chars)"
    }

def run_health_check():
    """Run all health checks and report results"""
    print("=" * 60)
    print("MEMORY AUTOMATION HEALTH CHECK")
    print("=" * 60)
    print()
    
    checks = [
        ("State File", check_state_file),
        ("Daily Files", check_daily_files),
        ("Session Summarization", check_session_summarization),
        ("Rollup Timestamps", check_rollup_timestamps),
        ("MEMORY.md", check_memory_md),
    ]
    
    results = {}
    for name, check_func in checks:
        result = check_func()
        results[name] = result
        
        # Color-code status
        status = result["status"]
        if status == "PASS":
            status_symbol = "✅"
        elif status == "WARN":
            status_symbol = "⚠️ "
        elif status == "FAIL":
            status_symbol = "❌"
        else:
            status_symbol = "ℹ️ "
        
        print(f"{status_symbol} {name}: {result['message']}")
    
    print()
    print("=" * 60)
    
    # Overall status
    fail_count = sum(1 for r in results.values() if r["status"] == "FAIL")
    warn_count = sum(1 for r in results.values() if r["status"] == "WARN")
    
    if fail_count > 0:
        print(f"OVERALL: {fail_count} failures, {warn_count} warnings")
        return 1
    elif warn_count > 0:
        print(f"OVERALL: {warn_count} warnings")
        return 0
    else:
        print("OVERALL: All systems operational ✅")
        return 0

if __name__ == "__main__":
    exit(run_health_check())
