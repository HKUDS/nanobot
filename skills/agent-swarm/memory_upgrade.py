#!/usr/bin/env python3
"""
Memory system upgrade with Timeline view
Extends existing MEMORY.md with chronological tracking
"""

import re
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path("/root/.nanobot/workspace/memory/MEMORY.md")

def parse_existing_memory():
    """Parse current MEMORY.md structure"""
    if not MEMORY_FILE.exists():
        return {}
    
    content = MEMORY_FILE.read_text(encoding='utf-8')
    
    # Extract sections
    sections = {}
    current_section = None
    current_content = []
    
    for line in content.split('\n'):
        if line.startswith('# ') or line.startswith('## '):
            if current_section:
                sections[current_section] = '\n'.join(current_content)
            current_section = line.strip('# ')
            current_content = []
        else:
            current_content.append(line)
    
    if current_section:
        sections[current_section] = '\n'.join(current_content)
    
    return sections

def add_timeline_entry(category: str, content: str, link: str = None, tags: list = None):
    """Add a new entry to Timeline section"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    tags_str = f" [{', '.join(tags)}]" if tags else ""
    link_str = f" → [{link}]" if link else ""
    
    entry = f"- **{timestamp}** [{category}]{tags_str} {content}{link_str}"
    
    # Read current memory
    if MEMORY_FILE.exists():
        memory_content = MEMORY_FILE.read_text(encoding='utf-8')
    else:
        memory_content = "# Memory\n\n"
    
    # Check if Timeline section exists
    if "## Timeline" not in memory_content:
        # Add Timeline section after the main header
        memory_content = memory_content.replace(
            "# Memory\n",
            "# Memory\n\n## Timeline\n\n" + entry + "\n\n"
        )
    else:
        # Add entry after Timeline header
        pattern = r"(## Timeline\n)"
        memory_content = re.sub(
            pattern,
            r"\1" + entry + "\n",
            memory_content
        )
    
    # Write back
    MEMORY_FILE.write_text(memory_content, encoding='utf-8')
    return entry

def get_recent_context(hours: int = 24) -> list:
    """Get timeline entries from last N hours"""
    if not MEMORY_FILE.exists():
        return []
    
    content = MEMORY_FILE.read_text(encoding='utf-8')
    
    # Extract Timeline section
    timeline_match = re.search(r'## Timeline\n(.*?)(?=##|$)', content, re.DOTALL)
    if not timeline_match:
        return []
    
    timeline_content = timeline_match.group(1)
    
    # Parse entries
    now = datetime.now()
    recent_entries = []
    
    for line in timeline_content.strip().split('\n'):
        if not line.strip():
            continue
        
        # Parse timestamp: - **2026-03-04 10:00** [...]
        time_match = re.search(r'- \*\*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\*\*', line)
        if time_match:
            entry_time = datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M")
            hours_ago = (now - entry_time).total_seconds() / 3600
            
            if hours_ago <= hours:
                recent_entries.append({
                    "time": time_match.group(1),
                    "content": line,
                    "hours_ago": hours_ago
                })
    
    return recent_entries

def search_timeline(keyword: str) -> list:
    """Search timeline for keyword"""
    if not MEMORY_FILE.exists():
        return []
    
    content = MEMORY_FILE.read_text(encoding='utf-8')
    
    # Extract Timeline section
    timeline_match = re.search(r'## Timeline\n(.*?)(?=##|$)', content, re.DOTALL)
    if not timeline_match:
        return []
    
    timeline_content = timeline_match.group(1)
    
    matches = []
    for line in timeline_content.strip().split('\n'):
        if keyword.lower() in line.lower():
            matches.append(line.strip())
    
    return matches

def format_context_for_prompt(hours: int = 24) -> str:
    """Format recent timeline entries for inclusion in prompt"""
    entries = get_recent_context(hours)
    
    if not entries:
        return "No recent context."
    
    lines = ["Recent activity:"]
    for entry in entries[:10]:  # Limit to 10 entries
        lines.append(f"- {entry['content'][2:]}")  # Remove the "- " prefix
    
    return '\n'.join(lines)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: memory_upgrade.py [add|recent|search] [args...]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "recent":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        entries = get_recent_context(hours)
        for e in entries:
            print(f"[{e['time']}] ({e['hours_ago']:.1f}h ago)")
            print(f"  {e['content']}")
            print()
    
    elif cmd == "search" and len(sys.argv) >= 3:
        keyword = sys.argv[2]
        matches = search_timeline(keyword)
        for m in matches:
            print(m)
    
    elif cmd == "add" and len(sys.argv) >= 4:
        category = sys.argv[2]
        content = sys.argv[3]
        link = sys.argv[4] if len(sys.argv) > 4 else None
        entry = add_timeline_entry(category, content, link)
        print(f"Added: {entry}")
