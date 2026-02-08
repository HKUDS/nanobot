#!/usr/bin/env python3
"""
Simplified memory extraction using direct prompting.
This version creates a standalone extraction prompt that can be used
manually or integrated into the rollup script.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List

import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_config import MEMORY_CONFIG


def create_extraction_prompt(daily_content: str) -> str:
    """
    Create an extraction prompt that can be sent to any LLM.
    Returns the prompt text.
    """
    prompt = f"""Extract atomic, structured memories from this daily log.

For EACH distinct fact/event/decision/insight:
1. Write ONE clear, self-contained sentence
2. Rate importance (1-10):
   - 1-3: Routine interaction, low long-term value
   - 4-6: Useful context, moderate importance
   - 7-8: Significant decision, key insight, important preference
   - 9-10: Critical milestone, major breakthrough, core identity info
3. Categorize:
   - episodic: Specific event ("User reported bug X at 10:30am")
   - semantic: General knowledge/preference ("User prefers async communication")
   - procedural: How-to/strategy ("Restart Redis fixes connection errors")
4. Add tags:
   - domain: health, tech, projects, personal, work
   - type: decision, insight, event, preference, issue, success, failure
   - priority: urgent, high, medium, low
   - entity: [relevant person/project/tool names]
   - sentiment: positive, neutral, negative, frustrated, excited

Only extract memories worth long-term retention (importance ≥ {MEMORY_CONFIG["MIN_IMPORTANCE_THRESHOLD"]}).

Daily Log:
{daily_content}

Return ONLY valid JSON array (no markdown, no extra text):
[
  {{
    "content": "...",
    "importance": 7,
    "category": "semantic",
    "tags": {{
      "domain": ["tech"],
      "type": ["preference"],
      "priority": ["medium"],
      "entity": ["Python"],
      "sentiment": ["positive"]
    }}
  }}
]
"""
    return prompt


def parse_extraction_response(response: str, session_id: str = None) -> List[dict]:
    """
    Parse LLM extraction response into memory objects.
    """
    # Extract JSON array
    json_start = response.find('[')
    json_end = response.rfind(']') + 1
    
    if json_start == -1 or json_end == 0:
        if 'no memories' in response.lower() or ('importance' in response.lower() and 'threshold' in response.lower()):
            print("LLM indicated no significant memories to extract")
            return []
        print(f"No JSON array found in response")
        return []
    
    json_str = response[json_start:json_end]
    
    try:
        memories_raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return []
    
    # Filter by importance threshold
    memories_raw = [m for m in memories_raw 
                    if m.get("importance", 0) >= MEMORY_CONFIG["MIN_IMPORTANCE_THRESHOLD"]]
    
    # Limit memories per day
    if len(memories_raw) > MEMORY_CONFIG["MAX_MEMORIES_PER_DAY"]:
        print(f"Warning: Extracted {len(memories_raw)} memories, limiting to {MEMORY_CONFIG['MAX_MEMORIES_PER_DAY']}")
        memories_raw.sort(key=lambda m: m.get("importance", 0), reverse=True)
        memories_raw = memories_raw[:MEMORY_CONFIG["MAX_MEMORIES_PER_DAY"]]
    
    # Enrich with metadata
    now = datetime.now(ZoneInfo("America/Edmonton"))
    memories = []
    for mem in memories_raw:
        mem["id"] = f"mem_{uuid.uuid4().hex[:8]}"
        mem["timestamp"] = now.isoformat()
        mem["access_count"] = 0
        mem["last_accessed"] = None
        mem["source_session"] = session_id
        mem["consolidated_from"] = []
        mem["superseded_by"] = None
        mem["status"] = "active"
        mem["embedding"] = None
        memories.append(mem)
    
    return memories


def append_to_memory_bank(memories: List[dict], memory_bank_path: Path):
    """Append memories to JSONL bank."""
    if not memories:
        return
    
    memory_bank_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(memory_bank_path, "a") as f:
        for mem in memories:
            f.write(json.dumps(mem) + "\n")
    
    print(f"✅ Appended {len(memories)} memories to {memory_bank_path.name}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract memories from daily log")
    parser.add_argument("--daily-file", help="Path to daily log file")
    parser.add_argument("--prompt-only", action="store_true", help="Just output the prompt")
    
    args = parser.parse_args()
    
    if args.daily_file:
        daily_content = Path(args.daily_file).read_text()
        
        if args.prompt_only:
            print(create_extraction_prompt(daily_content))
        else:
            print("This script creates extraction prompts.")
            print("Use --prompt-only to generate a prompt for manual use.")
            print("\nFor automatic extraction, use the rollup-daily.py script.")
