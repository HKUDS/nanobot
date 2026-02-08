#!/usr/bin/env python3
"""
Extract session start/end times in MST from JSONL file
Usage: python3 scripts/get-session-times.py <session-id>
"""

import sys
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if len(sys.argv) < 2:
    print("Usage: python3 scripts/get-session-times.py <session-id>")
    sys.exit(1)

session_id = sys.argv[1]
session_file = Path.home() / ".clawdbot/agents/main/sessions" / f"{session_id}.jsonl"

if not session_file.exists():
    print(f"Error: Session file not found: {session_file}")
    sys.exit(1)

# Read first and last lines
with open(session_file) as f:
    lines = f.readlines()
    first = json.loads(lines[0])
    last = json.loads(lines[-1])

# Parse timestamps (ISO format with Z)
start = datetime.fromisoformat(first['timestamp'].replace('Z', '+00:00'))
end = datetime.fromisoformat(last['timestamp'].replace('Z', '+00:00'))

# Convert to MST
mst = ZoneInfo('America/Edmonton')
start_mst = start.astimezone(mst)
end_mst = end.astimezone(mst)

# Output format for diary headers
print(f"{start_mst.strftime('%H:%M')}–{end_mst.strftime('%H:%M')}")
