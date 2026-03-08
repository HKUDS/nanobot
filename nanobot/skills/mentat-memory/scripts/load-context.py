#!/usr/bin/env python3
"""
Load all relevant memory context in attention-optimized order.

Phase 1: Check for unsummarized sessions (--check-sessions flag)
Phase 2: Load diary context in optimal order (no flag)

ADAPTED FOR NANOBOT: Uses ~/.nanobot/sessions/ instead of ~/.clawdbot/agents/main/sessions/
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def find_unsummarized_sessions(include_placeholders=False):
    """Scan session files and return list of sessions needing summarization.
    
    Args:
        include_placeholders: If True, include placeholder sessions (for debugging)
    
    Returns:
        List of dicts with {id, timestamp, date, file_path} for unsummarized sessions
    """
    state_file = Path("memory/diary/2026/.state.json")
    sessions_dir = Path.home() / ".nanobot" / "sessions"  # ADAPTED: nanobot path
    
    if not state_file.exists() or not sessions_dir.exists():
        return []
    
    try:
        with open(state_file) as f:
            state = json.load(f)
    except:
        return []
    
    last_summarized_id = state.get("lastSummarizedSessionId")
    private_sessions = set(state.get("privateSessions", []))
    # REMOVED: CLAWDBOT_SESSION_ID check (nanobot doesn't use env vars)
    
    # Scan all session files
    session_data = []
    for session_file in sorted(sessions_dir.glob("*.jsonl")):
        if ".deleted." in session_file.name or ".lock" in session_file.name:
            continue
        
        try:
            with open(session_file) as f:
                first_line = f.readline()
                if not first_line:
                    continue
                
                session_meta = json.loads(first_line)
                # ADAPTED: nanobot uses "_type": "metadata" instead of "type": "session"
                if session_meta.get("_type") != "metadata":
                    continue
                
                # ADAPTED: nanobot doesn't have session IDs in metadata
                # Use filename as session identifier
                session_id = session_file.stem  # e.g., "cli_direct"
                timestamp = session_meta.get("created_at", "")
                
                # Parse timestamp to get date
                try:
                    ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    mst = ZoneInfo('America/Edmonton')
                    session_date = ts.astimezone(mst).strftime('%Y-%m-%d')
                except:
                    session_date = "unknown"
                
                # REMOVED: subagent check (nanobot simpler architecture)
                
                # Skip private sessions
                if session_id in private_sessions:
                    continue
                
                # Check if has user messages (meaningful session)
                lines = f.readlines()
                has_user_messages = False
                user_message_count = 0
                first_message_time = None
                last_message_time = None
                
                for line in lines:
                    try:
                        msg = json.loads(line)
                        # ADAPTED: nanobot format is {"role": "user", "content": "...", "timestamp": "..."}
                        if msg.get("role") == "user":
                            content = msg.get("content", "")
                            # Skip system/bootstrap messages
                            if content and not content.startswith("You are a sub-agent") and not content.startswith("A new session was started"):
                                has_user_messages = True
                                user_message_count += 1
                                msg_time = msg.get("timestamp")
                                if first_message_time is None:
                                    first_message_time = msg_time
                                last_message_time = msg_time
                    except:
                        continue
                
                # Calculate session duration
                session_duration_minutes = 0
                if first_message_time and last_message_time:
                    try:
                        first_dt = datetime.fromisoformat(first_message_time.replace('Z', '+00:00'))
                        last_dt = datetime.fromisoformat(last_message_time.replace('Z', '+00:00'))
                        session_duration_minutes = (last_dt - first_dt).total_seconds() / 60
                    except:
                        pass
                
                # Filter placeholder sessions: <2 minutes AND zero user messages
                is_placeholder = (session_duration_minutes < 2 and user_message_count == 0)
                
                # Skip placeholders unless explicitly requested
                if is_placeholder and not include_placeholders:
                    continue
                
                if has_user_messages or is_placeholder:
                    session_data.append({
                        "id": session_id,
                        "timestamp": timestamp,
                        "date": session_date,
                        "file_path": str(session_file),
                        "is_placeholder": is_placeholder,
                        "user_messages": user_message_count,
                        "duration_minutes": round(session_duration_minutes, 2)
                    })
        except Exception as e:
            print(f"Warning: Error reading {session_file.name}: {e}", file=sys.stderr)
            continue
    
    # Sort by timestamp
    session_data.sort(key=lambda s: s["timestamp"])
    
    # Find unsummarized sessions (everything after lastSummarizedSessionId)
    if last_summarized_id is None:
        return session_data[:10]  # All sessions need summarization (limit 10)
    
    # Get timestamp of last summarized session
    last_summarized_timestamp = None
    for session in session_data:
        if session["id"] == last_summarized_id:
            last_summarized_timestamp = session["timestamp"]
            break
    
    # If we can't find the last summarized session, use a safety approach:
    # Take the last 5 sessions and filter out any that might already be summarized
    if last_summarized_timestamp is None:
        # Safety fallback: return most recent sessions
        return session_data[-5:]
    
    # Return all sessions AFTER the last summarized one
    unsummarized = [s for s in session_data if s["timestamp"] > last_summarized_timestamp]
    
    # Limit to 10 sessions max to avoid overwhelming system
    return unsummarized[:10]


def load_diary_context():
    """Load fractal diary context in attention-optimized order."""
    now = datetime.now(ZoneInfo("America/Edmonton"))
    year = now.year
    month = now.strftime("%Y-%m")
    week = now.strftime("%Y-W%V")
    day = now.strftime("%Y-%m-%d")
    
    base = Path("memory/diary") / str(year)
    sections = []
    
    # 1. Daily — MOST IMPORTANT (primacy bias works FOR us)
    daily_path = base / "daily" / f"{day}.md"
    if daily_path.exists():
        sections.append(f"=== TODAY ({day}) ===\n{daily_path.read_text()}\n")
    else:
        sections.append(f"=== TODAY ({day}) ===\n(No entries yet)\n")
    
    # 2. Weekly — recent patterns, high relevance
    weekly_path = base / "weekly" / f"{week}.md"
    if weekly_path.exists():
        sections.append(f"=== THIS WEEK ({week}) ===\n{weekly_path.read_text()}\n")
    else:
        sections.append(f"=== THIS WEEK ({week}) ===\n(No entries yet)\n")
    
    # 3. Monthly — broader trajectory
    monthly_path = base / "monthly" / f"{month}.md"
    if monthly_path.exists():
        sections.append(f"=== THIS MONTH ({month}) ===\n{monthly_path.read_text()}\n")
    else:
        sections.append(f"=== THIS MONTH ({month}) ===\n(No entries yet)\n")
    
    # 4. Annual — historical context (attention decay acceptable here)
    annual_path = base / "annual.md"
    if annual_path.exists():
        sections.append(f"=== THIS YEAR ({year}) ===\n{annual_path.read_text()}\n")
    else:
        sections.append(f"=== THIS YEAR ({year}) ===\n(No entries yet)\n")
    
    return "\n".join(sections)


def init_startup_state():
    """Initialize startup state tracking file."""
    state_file = Path(".startup-state.json")
    state = {
        "timestamp": datetime.now().isoformat(),
        "load_context_executed": False,
        "sessions_checked": False,
        "soul_loaded": False,
        "user_loaded": False,
        "memory_loaded": False,
        "diary_loaded": False
    }
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    return state_file


def update_startup_state(key, value=True):
    """Update a specific step in the startup state."""
    state_file = Path(".startup-state.json")
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
    else:
        state = init_startup_state()
        with open(state_file) as f:
            state = json.load(f)
    
    state[key] = value
    state["timestamp"] = datetime.now().isoformat()
    
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


if __name__ == "__main__":
    include_placeholders = "--include-placeholders" in sys.argv
    
    if "--check-sessions" in sys.argv:
        # Phase 1: Check for unsummarized sessions
        # Initialize startup state tracking
        init_startup_state()
        update_startup_state("load_context_executed", True)
        update_startup_state("sessions_checked", True)
        
        unsummarized = find_unsummarized_sessions(include_placeholders)
        
        if unsummarized:
            print("SUMMARIZE_PENDING")
            for session in unsummarized:
                # Output format: session_id|date|file_path|placeholder|user_msgs|duration
                placeholder_flag = "PLACEHOLDER" if session.get("is_placeholder", False) else "NORMAL"
                print(f"{session['id']}|{session['date']}|{session['file_path']}|{placeholder_flag}|{session.get('user_messages', 0)}|{session.get('duration_minutes', 0)}")
        else:
            print("READY")
    else:
        # Phase 2: Load diary context
        update_startup_state("load_context_executed", True)
        update_startup_state("diary_loaded", True)
        print(load_diary_context())
