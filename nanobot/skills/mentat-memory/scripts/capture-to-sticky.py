#!/usr/bin/env python3
"""
Sticky note capture utility
Extracts key information and routes to appropriate sticky note files

Usage:
    python3 scripts/capture-to-sticky.py --domain tech --file commands --fact "git reset --hard HEAD"
    python3 scripts/capture-to-sticky.py --domain health --file training-insights --fact "Best recovery is 48h between heavy lifts"
    python3 scripts/capture-to-sticky.py --domain projects --file active --section "Memory System" --fact "Fractal diary uses 4 levels: daily/weekly/monthly/annual"
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).parent.parent
STICKY_ROOT = WORKSPACE / "memory" / "sticky-notes"

DOMAINS = {
    "health": STICKY_ROOT / "health",
    "tech": STICKY_ROOT / "tech",
    "projects": STICKY_ROOT / "projects",
    "survival": STICKY_ROOT / "survival"
}

def capture_fact(domain: str, filename: str, fact: str, section: str = None):
    """Capture a fact to a sticky note file"""
    if domain not in DOMAINS:
        print(f"Error: Unknown domain '{domain}'. Use: {', '.join(DOMAINS.keys())}")
        sys.exit(1)
    
    domain_path = DOMAINS[domain]
    domain_path.mkdir(parents=True, exist_ok=True)
    
    file_path = domain_path / f"{filename}.md"
    
    # Check if file exists, create if not
    if not file_path.exists():
        file_path.write_text(f"# {filename.replace('-', ' ').title()}\n\n")
    
    content = file_path.read_text()
    
    # Check for duplication (simple substring check)
    if fact.lower() in content.lower():
        print(f"ℹ Fact already exists in {file_path.name}")
        return
    
    # Append to section or end of file
    if section:
        section_header = f"## {section}"
        if section_header not in content:
            content = content.rstrip() + f"\n\n{section_header}\n"
        
        # Find section and append
        lines = content.split('\n')
        section_idx = None
        next_section_idx = None
        
        for i, line in enumerate(lines):
            if line.strip() == section_header:
                section_idx = i
            elif section_idx is not None and line.startswith("## "):
                next_section_idx = i
                break
        
        if section_idx is not None:
            entry = f"- {fact}"
            if next_section_idx:
                lines.insert(next_section_idx, entry)
            else:
                lines.append(entry)
        
        content = '\n'.join(lines)
    else:
        # Append to end
        content = content.rstrip() + f"\n- {fact}\n"
    
    file_path.write_text(content)
    print(f"✓ Captured to {domain}/{filename}.md")

def main():
    parser = argparse.ArgumentParser(description="Capture facts to sticky notes")
    parser.add_argument("--domain", required=True, choices=DOMAINS.keys(), 
                       help="Domain category")
    parser.add_argument("--file", required=True, 
                       help="Filename (without .md extension)")
    parser.add_argument("--fact", required=True, 
                       help="Fact to capture")
    parser.add_argument("--section", 
                       help="Section within file (optional)")
    
    args = parser.parse_args()
    
    capture_fact(args.domain, args.file, args.fact, args.section)

if __name__ == "__main__":
    main()
