#!/usr/bin/env python3
"""
Real-time diary logging utility
Appends events/notes to today's daily diary file during active sessions

Usage:
    python3 scripts/log-to-diary.py --event "Completed task X"
    python3 scripts/log-to-diary.py --note "Observed pattern Y"
    python3 scripts/log-to-diary.py --decision "Decided to implement Z"
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"

def get_today_diary_path():
    """Get path to today's daily diary file"""
    now = datetime.now(ZoneInfo("America/Edmonton"))
    year = now.year
    day = now.strftime("%Y-%m-%d")
    
    daily_dir = DIARY_ROOT / str(year) / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    
    diary_path = daily_dir / f"{day}.md"
    
    # Initialize file if it doesn't exist
    if not diary_path.exists():
        diary_path.write_text(f"# {day} ({now.strftime('%A')})\n\n## Sessions\n\n")
    
    return diary_path

def append_entry(section: str, content: str, timestamp: bool = True):
    """Append an entry to the appropriate section of today's diary"""
    diary_path = get_today_diary_path()
    current_content = diary_path.read_text()
    
    # Get current time for timestamp
    now = datetime.now(ZoneInfo("America/Edmonton"))
    time_str = now.strftime("%H:%M") if timestamp else ""
    
    # Determine section header
    section_headers = {
        "event": "## Events",
        "note": "## Notes",
        "decision": "## Decisions",
        "work": "## Work Completed"
    }
    
    section_header = section_headers.get(section, f"## {section.title()}")
    
    # Check if section exists
    if section_header not in current_content:
        # Add section at end
        current_content = current_content.rstrip() + f"\n\n{section_header}\n"
    
    # Format entry
    if timestamp and time_str:
        entry = f"- [{time_str}] {content}\n"
    else:
        entry = f"- {content}\n"
    
    # Find section and append
    lines = current_content.split('\n')
    section_index = None
    next_section_index = None
    
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            section_index = i
        elif section_index is not None and line.startswith("## "):
            next_section_index = i
            break
    
    if section_index is not None:
        if next_section_index is not None:
            # Insert before next section
            lines.insert(next_section_index, entry.rstrip())
        else:
            # Append to end of section
            lines.append(entry.rstrip())
    
    # Write back
    diary_path.write_text('\n'.join(lines))
    print(f"✓ Logged to {diary_path.name}")

def main():
    parser = argparse.ArgumentParser(description="Log entries to today's diary")
    parser.add_argument("--event", type=str, help="Log an event")
    parser.add_argument("--note", type=str, help="Log a note/observation")
    parser.add_argument("--decision", type=str, help="Log a decision")
    parser.add_argument("--work", type=str, help="Log completed work")
    parser.add_argument("--section", type=str, help="Custom section name")
    parser.add_argument("--content", type=str, help="Content for custom section")
    parser.add_argument("--no-timestamp", action="store_true", help="Don't add timestamp")
    
    args = parser.parse_args()
    
    timestamp = not args.no_timestamp
    
    if args.event:
        append_entry("event", args.event, timestamp)
    elif args.note:
        append_entry("note", args.note, timestamp)
    elif args.decision:
        append_entry("decision", args.decision, timestamp)
    elif args.work:
        append_entry("work", args.work, timestamp)
    elif args.section and args.content:
        append_entry(args.section, args.content, timestamp)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
