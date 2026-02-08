#!/usr/bin/env python3
"""
Enhanced daily rollup with memory extraction.
This version uses file-based LLM interaction for better reliability.
"""
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_config import MEMORY_CONFIG
from memory_extraction_simple import create_extraction_prompt, parse_extraction_response, append_to_memory_bank

WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"
MEMORY_BANK = Path(MEMORY_CONFIG["MEMORY_BANK_PATH"])


def get_week_number(date):
    """Get ISO week number (YYYY-Wnn format)"""
    return date.strftime("%Y-W%V")


def extract_memories_via_agent(daily_content: str) -> list:
    """
    Extract memories using clawdbot agent command.
    Returns list of memory objects.
    """
    prompt = create_extraction_prompt(daily_content)
    
    # Write prompt to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(prompt)
        prompt_file = f.name
    
    try:
        import subprocess
        
        # Use clawdbot agent with a temporary session
        result = subprocess.run(
            ["clawdbot", "agent", 
             "--local",  # Run locally without gateway
             "--message", prompt,
             "--json"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            print(f"Agent call failed: {result.stderr}")
            return []
        
        # Parse JSON output
        output_data = json.loads(result.stdout)
        response_text = output_data.get("message", {}).get("content", "")
        
        if isinstance(response_text, list):
            response_text = " ".join([c.get("text", "") for c in response_text if c.get("type") == "text"])
        
        # Parse extraction response
        memories = parse_extraction_response(response_text)
        return memories
        
    except Exception as e:
        print(f"Error during memory extraction: {e}")
        return []
    finally:
        # Clean up temp file
        try:
            Path(prompt_file).unlink()
        except:
            pass


def rollup_daily_to_weekly():
    """
    Enhanced daily rollup with memory extraction.
    """
    today = datetime.now(ZoneInfo("America/Edmonton"))
    year = today.year
    
    daily_file = DIARY_ROOT / str(year) / "daily" / f"{today.strftime('%Y-%m-%d')}.md"
    week_num = get_week_number(today)
    weekly_file = DIARY_ROOT / str(year) / "weekly" / f"{week_num}.md"
    
    if not daily_file.exists():
        print(f"No daily file found: {daily_file}")
        return
    
    # Read daily content
    with open(daily_file) as f:
        daily_content = f.read()
    
    # Phase 1: Extract structured memories
    memories = []
    if MEMORY_CONFIG["ENABLE_STRUCTURED_EXTRACTION"]:
        print(f"Extracting atomic memories from {daily_file.name}...")
        try:
            memories = extract_memories_via_agent(daily_content)
            
            if memories:
                append_to_memory_bank(memories, MEMORY_BANK)
            else:
                print(f"No significant memories extracted (importance < {MEMORY_CONFIG['MIN_IMPORTANCE_THRESHOLD']})")
        except Exception as e:
            print(f"Memory extraction failed: {e}")
            print("Falling back to narrative summary only")
    
    # Phase 2: Generate narrative summary
    # For now, use a simple summary (can enhance with LLM later)
    if memories:
        summary_lines = [f"- {m['content']}" for m in memories[:5]]  # Top 5 memories
        summary_content = "\n".join(summary_lines)
    else:
        summary_content = "_No significant events recorded._"
    
    summary = f"\n## {today.strftime('%A, %B %d')}\n"
    summary += summary_content + "\n"
    
    # Append to weekly
    weekly_file.parent.mkdir(parents=True, exist_ok=True)
    
    if not weekly_file.exists():
        weekly_content = f"# Week {week_num}\n\n"
        weekly_content += f"## Overview\n_To be populated by weekly rollup_\n\n"
        weekly_content += f"## Daily Summaries\n"
    else:
        with open(weekly_file) as f:
            weekly_content = f.read()
    
    # Append summary
    with open(weekly_file, "w") as f:
        f.write(weekly_content + summary)
    
    print(f"✅ Rolled up {daily_file.name} → {weekly_file.name}")
    if memories:
        print(f"   Extracted {len(memories)} structured memories")


if __name__ == "__main__":
    rollup_daily_to_weekly()
