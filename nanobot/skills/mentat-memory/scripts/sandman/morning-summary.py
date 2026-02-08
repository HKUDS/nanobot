#!/usr/bin/env python3
"""
Sandman Morning Summary
Reads overnight analysis results and creates a concise morning briefing.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

WORKSPACE = Path('/home/deva/shared')
SANDMAN_DIR = WORKSPACE / 'memory/sandman'
STATE_FILE = WORKSPACE / 'memory/.sandman-state.json'

def load_state():
    """Load sandman state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def get_todays_reports():
    """Find all sandman reports from today."""
    today = datetime.now().strftime('%Y-%m-%d')
    if not SANDMAN_DIR.exists():
        return []
    
    reports = []
    for file in SANDMAN_DIR.glob(f'{today}-*.md'):
        task_id = file.stem.replace(f'{today}-', '')
        try:
            content = file.read_text()
            reports.append({
                'task_id': task_id,
                'file': str(file),
                'content': content
            })
        except Exception as e:
            print(f"Error reading {file}: {e}", file=sys.stderr)
    
    return reports

def generate_summary():
    """Generate a concise morning summary."""
    state = load_state()
    reports = get_todays_reports()
    
    if not reports:
        return None
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    summary = f"""# 🌙 Sandman Morning Report - {today}

**Overnight Analysis Complete**

Sandman ran {len(reports)} analysis tasks last night. Here's what I found:

"""
    
    for report in reports:
        # Extract key insights (first few paragraphs or bullet points)
        lines = report['content'].split('\n')
        task_name = report['task_id'].replace('_', ' ').title()
        
        summary += f"## {task_name}\n\n"
        
        # Get first meaningful section (skip headers)
        content_started = False
        line_count = 0
        for line in lines:
            if line.strip() and not line.startswith('#'):
                content_started = True
            if content_started and line.strip():
                summary += line + '\n'
                line_count += 1
                if line_count >= 8:  # First ~8 lines of content
                    break
        
        summary += f"\n📄 *Full report: `{report['file']}`*\n\n---\n\n"
    
    # Add spend info
    sandman_spent = state.get('sandman_daily_spend', 0.0)
    summary += f"\n**Budget:** Spent ${sandman_spent:.2f} of $5.00 overnight\n"
    
    return summary

def main():
    """Generate and output morning summary."""
    summary = generate_summary()
    
    if summary:
        print(summary)
        
        # Also save to a file
        today = datetime.now().strftime('%Y-%m-%d')
        summary_file = WORKSPACE / 'memory/sandman' / f'{today}-MORNING-SUMMARY.md'
        summary_file.write_text(summary)
        
        return 0
    else:
        print("No sandman reports found for today.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
