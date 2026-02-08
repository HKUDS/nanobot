#!/usr/bin/env python3
"""
Summarize a single session (executed by subagent).

This script is invoked by a subagent spawned via sessions_spawn tool.
It reads the session JSONL, writes a diary entry, and updates state.

Usage (by subagent): 
  python3 scripts/summarize-session-direct.py <session-id>
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def summarize_session(session_id):
    """Read session, extract key info, write to diary, update state."""
    
    # 1. Find session file
    session_file = Path.home() / ".nanobot/sessions" / f"{session_id}.jsonl"
    if not session_file.exists():
        print(f"ERROR: Session file not found: {session_file}")
        return False
    
    # 2. Read session metadata and messages
    try:
        with open(session_file) as f:
            lines = f.readlines()
        
        # Extract start/end times
        first_meta = json.loads(lines[0])
        
        # Find first and last message with timestamp
        messages_with_ts = []
        for line in lines[1:]:
            entry = json.loads(line)
            if 'timestamp' in entry:
                messages_with_ts.append(entry)
        
        if not messages_with_ts:
            print(f"ERROR: No messages found in session")
            return False
        
        first_msg = messages_with_ts[0]
        last_msg = messages_with_ts[-1]
        
        start_ts = datetime.fromisoformat(first_msg['timestamp'].replace('Z', '+00:00'))
        end_ts = datetime.fromisoformat(last_msg['timestamp'].replace('Z', '+00:00'))
        
        # Convert to MST
        mst = ZoneInfo('America/Edmonton')
        start_mst = start_ts.astimezone(mst)
        end_mst = end_ts.astimezone(mst)
        session_date = start_mst.strftime('%Y-%m-%d')
        time_range = f"{start_mst.strftime('%H:%M')}–{end_mst.strftime('%H:%M')}"
        
        # Extract user and assistant messages
        user_messages = []
        assistant_messages = []
        tool_calls = []
        
        for line in lines[1:]:  # Skip first line (session metadata)
            try:
                entry = json.loads(line)
                role = entry.get("role")
                content = entry.get("content", "")
                
                if role == "user":
                    if content and not content.startswith("Read HEARTBEAT.md"):
                        user_messages.append(content)
                elif role == "assistant":
                    if content:
                        assistant_messages.append(content)
                
                # Check for tool_calls field
                if "tool_calls" in entry:
                    for tc in entry["tool_calls"]:
                        tool_calls.append(tc.get("function", {}).get("name", "unknown"))
                        
            except:
                continue
        
        # 3. Build context string for LLM to analyze
        context = f"""Session from {session_date} ({time_range} MST)

USER MESSAGES ({len(user_messages)}):
"""
        for i, msg in enumerate(user_messages[:15], 1):  # Limit to avoid token overflow
            msg_display = msg[:300] + "..." if len(msg) > 300 else msg
            context += f"{i}. {msg_display}\n"
        
        context += f"\nASSISTANT MESSAGES ({len(assistant_messages)}):\n"
        for i, msg in enumerate(assistant_messages[:15], 1):
            msg_display = msg[:300] + "..." if len(msg) > 300 else msg
            context += f"{i}. {msg_display}\n"
        
        if tool_calls:
            context += f"\nTOOLS USED: {', '.join(set(tool_calls))}\n"
        
        # 4. Prompt for reflective summary (this is for the subagent to process)
        # The subagent will read this context and write the reflection
        print(f"SESSION_CONTEXT_START")
        print(context)
        print(f"SESSION_CONTEXT_END")
        print(f"SESSION_ID:{session_id}")
        print(f"DATE:{session_date}")
        print(f"TIME_RANGE:{time_range}")
        
        # 5. Critical instruction for subagent
        print(f"\n⚠️ SUMMARIZATION INSTRUCTION:")
        print(f"Pay special attention to: requests for memory tests, secret words, personal context,")
        print(f"emotional tone, relationship dynamics. These are NOT noise—they're signal.")
        print(f"Capture: test canaries, conversation patterns, humor, frustration, connection moments.")
        print(f"Don't filter out the human stuff. That's what matters most.")
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to process session {session_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR: Usage: python3 scripts/summarize-session-direct.py <session-id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    success = summarize_session(session_id)
    sys.exit(0 if success else 1)
