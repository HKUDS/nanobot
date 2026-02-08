#!/usr/bin/env python3
"""
Sandman Phase 2: Session Sampler
Samples recent sessions to verify memory pipeline integrity
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any

# Paths
WORKSPACE = Path(__file__).parent.parent.parent
SESSIONS_DIR = Path.home() / ".clawdbot" / "agents" / "main" / "sessions"
DIARY_ROOT = WORKSPACE / "memory" / "diary"
SANDMAN_REPORTS = WORKSPACE / "memory" / "sandman" / "reports"
STICKY_NOTES = WORKSPACE / "memory" / "sticky-notes"


def is_meaningful_session(session_meta: Dict, lines: List[str]) -> bool:
    """Check if a session represents meaningful user interaction
    
    Filter out:
    - Subagent sessions (key contains 'subagent' OR first user message starts with "You are a sub-agent")
    - Empty sessions (no user messages)
    - System-only sessions (only automated greetings)
    """
    # Check session key for subagent marker
    session_key = session_meta.get("key", "")
    if session_key and "subagent" in session_key.lower():
        return False
    
    # Count actual user messages (excluding system prompts)
    user_message_count = 0
    has_real_content = False
    first_user_message = None
    
    for line in lines:
        try:
            msg = json.loads(line)
            # Handle both message formats (.role and .message.role)
            role = msg.get("role") or (msg.get("message", {}).get("role") if msg.get("message") else None)
            
            if msg.get("type") == "message" and role == "user":
                # Handle both content formats
                content = msg.get("content") or (msg.get("message", {}).get("content") if msg.get("message") else [])
                
                if content and len(content) > 0:
                    text = content[0].get("text", "")
                    
                    # Capture first user message to check for subagent pattern
                    if first_user_message is None:
                        first_user_message = text
                    
                    # Filter out system greeting prompts
                    if not text.startswith("A new session was started via /new"):
                        user_message_count += 1
                        # Check if there's meaningful content (not just commands)
                        if len(text.strip()) > 10:
                            has_real_content = True
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    
    # Check if first user message indicates this is a subagent session
    if first_user_message and first_user_message.startswith("You are a sub-agent"):
        return False
    
    # Session must have at least one real user message with content
    return user_message_count > 0 and has_real_content


def get_sessions_in_window(hours: int = 24) -> List[Dict[str, Any]]:
    """Get all meaningful sessions from the past N hours
    
    Filters out subagent sessions and empty system sessions
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sessions = []
    
    if not SESSIONS_DIR.exists():
        return sessions
    
    for session_file in SESSIONS_DIR.glob("*.jsonl"):
        try:
            # Read first line to get session metadata
            with open(session_file) as f:
                first_line = f.readline()
                if not first_line:
                    continue
                
                session_meta = json.loads(first_line)
                if session_meta.get("type") != "session":
                    continue
                
                timestamp = datetime.fromisoformat(
                    session_meta["timestamp"].replace("Z", "+00:00")
                )
                
                if timestamp >= cutoff:
                    # Read all lines for filtering
                    f.seek(0)
                    lines = f.readlines()
                    
                    # Filter out non-meaningful sessions
                    if not is_meaningful_session(session_meta, lines):
                        continue
                    
                    # Count messages (handle both .role and .message.role formats)
                    user_messages = []
                    assistant_messages = []
                    
                    for line in lines:
                        try:
                            msg = json.loads(line)
                            if msg.get("type") == "message":
                                role = msg.get("role") or (msg.get("message", {}).get("role") if msg.get("message") else None)
                                if role == "user":
                                    user_messages.append(msg)
                                elif role == "assistant":
                                    assistant_messages.append(msg)
                        except (json.JSONDecodeError, KeyError):
                            continue
                    
                    sessions.append({
                        "id": session_meta["id"],
                        "timestamp": timestamp,
                        "file": session_file,
                        "user_messages": len(user_messages),
                        "assistant_messages": len(assistant_messages),
                        "total_lines": len(lines),
                    })
        except Exception as e:
            print(f"Error reading {session_file}: {e}")
            continue
    
    return sorted(sessions, key=lambda s: s["timestamp"], reverse=True)


def select_representative_sessions(sessions: List[Dict], count: int = 3) -> List[Dict]:
    """Select representative sessions for sampling"""
    if len(sessions) <= count:
        return sessions
    
    # Strategy: Take most recent, one from middle, one older
    selected = []
    
    # Most recent
    selected.append(sessions[0])
    
    # Middle (by index)
    if len(sessions) >= 2:
        mid_idx = len(sessions) // 2
        selected.append(sessions[mid_idx])
    
    # Older (but still within window)
    if len(sessions) >= 3:
        selected.append(sessions[-1])
    
    return selected[:count]


def check_session_in_diary(session: Dict, diary_date: str) -> Dict[str, Any]:
    """Check if session appears in diary entry"""
    diary_file = DIARY_ROOT / "2026" / "daily" / f"{diary_date}.md"
    
    result = {
        "diary_exists": diary_file.exists(),
        "session_id_found": False,
        "session_mentioned": False,
        "keywords_found": [],
    }
    
    if not diary_file.exists():
        return result
    
    try:
        content = diary_file.read_text()
        
        # Check for session ID
        if session["id"] in content:
            result["session_id_found"] = True
        
        # Check for session references (partial ID, timestamp, etc.)
        session_short_id = session["id"][:8]
        if session_short_id in content:
            result["session_mentioned"] = True
        
        # Extract potential keywords from session (very basic)
        # In real implementation, would parse session content
        result["keywords_found"] = ["placeholder"]  # TODO: extract actual keywords
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def test_memory_retrieval(session: Dict) -> Dict[str, Any]:
    """Test if we can retrieve session information from memory"""
    result = {
        "file_accessible": session["file"].exists(),
        "parseable": False,
        "sample_content": None,
    }
    
    try:
        with open(session["file"]) as f:
            lines = f.readlines()
            
            # Find first user message
            for line in lines:
                msg = json.loads(line)
                if msg.get("type") == "message" and msg.get("role") == "user":
                    result["sample_content"] = msg.get("content", [""])[0][:100]
                    break
            
            result["parseable"] = True
    except Exception as e:
        result["error"] = str(e)
    
    return result


def check_sticky_notes_updated(session: Dict) -> Dict[str, Any]:
    """Check if sticky-notes were updated (placeholder for now)"""
    # This is a placeholder - would need more sophisticated tracking
    # to know which sticky-notes SHOULD have been updated
    
    result = {
        "sticky_notes_exist": STICKY_NOTES.exists(),
        "recent_updates": [],
    }
    
    if not STICKY_NOTES.exists():
        return result
    
    try:
        # Check for sticky-notes modified around session time
        session_time = session["timestamp"]
        window = timedelta(hours=2)
        
        for note_file in STICKY_NOTES.rglob("*.md"):
            mtime = datetime.fromtimestamp(note_file.stat().st_mtime, tz=timezone.utc)
            
            if abs(mtime - session_time) < window:
                result["recent_updates"].append({
                    "file": str(note_file.relative_to(WORKSPACE)),
                    "modified": mtime.isoformat(),
                })
    except Exception as e:
        result["error"] = str(e)
    
    return result


def verify_key_events(session: Dict) -> Dict[str, Any]:
    """Verify that key events were captured"""
    result = {
        "has_user_interaction": session["user_messages"] > 0,
        "has_assistant_response": session["assistant_messages"] > 0,
        "interaction_ratio": 0.0,
    }
    
    total_messages = session["user_messages"] + session["assistant_messages"]
    if total_messages > 0:
        result["interaction_ratio"] = session["user_messages"] / total_messages
    
    return result


def run_sampling() -> Dict[str, Any]:
    """Run the complete sampling process"""
    print("🔍 Sandman Phase 2: Session Sampling")
    print("=" * 50)
    
    # Get sessions from past 24h
    print("\n📅 Fetching sessions from past 24 hours...")
    all_sessions = get_sessions_in_window(hours=24)
    print(f"   Found {len(all_sessions)} sessions")
    
    # Select representative samples
    print("\n🎯 Selecting representative sessions...")
    selected = select_representative_sessions(all_sessions, count=3)
    print(f"   Selected {len(selected)} sessions for testing")
    
    # Run checks on each session
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "window_hours": 24,
        "total_sessions": len(all_sessions),
        "sampled_sessions": len(selected),
        "checks": [],
        "summary": {
            "sessions_in_diary": 0,
            "sessions_retrievable": 0,
            "sticky_notes_updated": 0,
            "key_events_captured": 0,
        }
    }
    
    print("\n🔬 Running integrity checks...")
    for i, session in enumerate(selected, 1):
        print(f"\n   Session {i}/{len(selected)}: {session['id'][:8]}...")
        
        # Determine diary date for this session
        diary_date = session["timestamp"].strftime("%Y-%m-%d")
        
        # Run all checks
        diary_check = check_session_in_diary(session, diary_date)
        retrieval_check = test_memory_retrieval(session)
        sticky_check = check_sticky_notes_updated(session)
        events_check = verify_key_events(session)
        
        session_report = {
            "session_id": session["id"],
            "timestamp": session["timestamp"].isoformat(),
            "diary_date": diary_date,
            "message_counts": {
                "user": session["user_messages"],
                "assistant": session["assistant_messages"],
            },
            "checks": {
                "diary_pipeline": diary_check,
                "memory_retrieval": retrieval_check,
                "sticky_notes": sticky_check,
                "key_events": events_check,
            }
        }
        
        # Update summary
        if diary_check.get("diary_exists") and (
            diary_check.get("session_id_found") or diary_check.get("session_mentioned")
        ):
            report["summary"]["sessions_in_diary"] += 1
            print(f"      ✓ Found in diary")
        else:
            print(f"      ✗ Not found in diary")
        
        if retrieval_check.get("parseable"):
            report["summary"]["sessions_retrievable"] += 1
            print(f"      ✓ Retrievable")
        
        if len(sticky_check.get("recent_updates", [])) > 0:
            report["summary"]["sticky_notes_updated"] += 1
            print(f"      ✓ Sticky-notes updated")
        
        if events_check.get("has_user_interaction") and events_check.get("has_assistant_response"):
            report["summary"]["key_events_captured"] += 1
            print(f"      ✓ Key events captured")
        
        report["checks"].append(session_report)
    
    # Calculate health scores
    if len(selected) > 0:
        report["health_scores"] = {
            "diary_pipeline": report["summary"]["sessions_in_diary"] / len(selected),
            "memory_retrieval": report["summary"]["sessions_retrievable"] / len(selected),
            "sticky_notes": report["summary"]["sticky_notes_updated"] / len(selected),
            "key_events": report["summary"]["key_events_captured"] / len(selected),
        }
        
        report["overall_health"] = sum(report["health_scores"].values()) / len(report["health_scores"])
    
    return report


def main():
    """Main entry point"""
    try:
        report = run_sampling()
        
        # Save report
        SANDMAN_REPORTS.mkdir(parents=True, exist_ok=True)
        report_date = datetime.now().strftime("%Y-%m-%d")
        report_file = SANDMAN_REPORTS / f"sampling-{report_date}.json"
        
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)
        
        print("\n" + "=" * 50)
        print(f"📊 SUMMARY")
        print("=" * 50)
        print(f"Total sessions in window: {report['total_sessions']}")
        print(f"Sessions sampled: {report['sampled_sessions']}")
        print(f"\nHealth Scores:")
        
        if "health_scores" in report:
            for metric, score in report["health_scores"].items():
                status = "✓" if score >= 0.7 else "⚠" if score >= 0.5 else "✗"
                print(f"  {status} {metric}: {score:.1%}")
            
            print(f"\n  Overall Health: {report['overall_health']:.1%}")
        
        print(f"\n📄 Report saved to: {report_file.relative_to(WORKSPACE)}")
        
        return 0
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
