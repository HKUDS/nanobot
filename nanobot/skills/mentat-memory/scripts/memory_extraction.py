#!/usr/bin/env python3
"""
Structured memory extraction from daily logs.
Converts narrative text into atomic memory objects with importance scoring.
"""
import json
import uuid
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Optional
from memory_config import MEMORY_CONFIG


def extract_atomic_memories(daily_content: str, session_id: Optional[str] = None) -> List[dict]:
    """
    LLM-based extraction of structured memories from daily log.
    
    Returns list of MemoryObject dicts.
    """
    if not MEMORY_CONFIG["ENABLE_STRUCTURED_EXTRACTION"]:
        return []
    
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
  }},
  ...
]
"""
    
    try:
        result = subprocess.run(
            ["clawdbot", "sessions", "spawn", 
             "--model", "flash",  # Use cheaper model for extraction
             "--cleanup", "delete", 
             "--label", "Memory Extraction", 
             prompt],
            capture_output=True, 
            text=True, 
            timeout=60
        )
        
        if result.returncode != 0:
            print(f"Extraction failed: {result.stderr}")
            return []
        
        # Parse JSON response
        output = result.stdout.strip()
        
        # The output includes metadata lines before the actual response
        # Look for the actual LLM response after "Flags" line
        lines = output.split('\n')
        llm_output_start = 0
        for i, line in enumerate(lines):
            if 'Flags' in line or 'direct' in line:
                llm_output_start = i + 1
                break
        
        # Rejoin from actual LLM response
        llm_output = '\n'.join(lines[llm_output_start:])
        
        # Extract JSON array (LLM might add explanation before/after)
        json_start = llm_output.find('[')
        json_end = llm_output.rfind(']') + 1
        if json_start == -1 or json_end == 0:
            # Check if LLM said there's nothing to extract
            if 'no memories' in llm_output.lower() or 'importance' in llm_output.lower() and 'threshold' in llm_output.lower():
                print(f"LLM indicated no significant memories to extract")
                return []
            print(f"No JSON array found in LLM output: {llm_output[:300]}")
            return []
        
        json_str = llm_output[json_start:json_end]
        memories_raw = json.loads(json_str)
        
        # Filter by importance threshold
        memories_raw = [m for m in memories_raw 
                        if m.get("importance", 0) >= MEMORY_CONFIG["MIN_IMPORTANCE_THRESHOLD"]]
        
        # Limit memories per day to prevent explosion
        if len(memories_raw) > MEMORY_CONFIG["MAX_MEMORIES_PER_DAY"]:
            print(f"Warning: Extracted {len(memories_raw)} memories, limiting to {MEMORY_CONFIG['MAX_MEMORIES_PER_DAY']}")
            # Sort by importance and take top N
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
            mem["embedding"] = None  # Compute later if needed
            memories.append(mem)
        
        return memories
    
    except Exception as e:
        print(f"Failed to extract memories: {e}")
        return []


def append_to_memory_bank(memories: List[dict], memory_bank_path: Path):
    """
    Append extracted memories to JSONL memory bank.
    """
    if not memories:
        return
    
    memory_bank_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(memory_bank_path, "a") as f:
        for mem in memories:
            f.write(json.dumps(mem) + "\n")
    
    print(f"✅ Appended {len(memories)} memories to {memory_bank_path.name}")


def generate_narrative_summary(memories: List[dict]) -> str:
    """
    Convert structured memories back to narrative for weekly summary.
    Maintains human-readable weekly files.
    """
    if not memories:
        return "_No significant memories extracted._"
    
    # Create a condensed representation for the LLM
    memory_summary = []
    for mem in memories:
        memory_summary.append({
            "content": mem["content"],
            "importance": mem["importance"],
            "category": mem["category"]
        })
    
    prompt = f"""Create a concise narrative summary from these structured memories:

{json.dumps(memory_summary, indent=2)}

Guidelines:
- 3-5 sentences maximum
- Past tense
- Cohesive narrative, not bullet points
- Highlight highest-importance items
- Capture overall themes

Example: "Made significant progress on dashboard optimization, addressing performance issues that caused 5+ second load times. Clarified preference for Python in backend development. Resolved several Redis connection errors through service restarts."
"""
    
    try:
        result = subprocess.run(
            ["clawdbot", "sessions", "spawn", 
             "--model", "flash",
             "--cleanup", "delete", 
             "--label", "Narrative Summary", 
             prompt],
            capture_output=True, 
            text=True, 
            timeout=30
        )
        
        if result.returncode == 0:
            output = result.stdout.strip()
            
            # Extract actual LLM response (skip metadata)
            lines = output.split('\n')
            llm_start = 0
            for i, line in enumerate(lines):
                if 'Flags' in line or 'direct' in line:
                    llm_start = i + 1
                    break
            
            summary = '\n'.join(lines[llm_start:]).strip()
            
            # Clean up any markdown or artifacts
            if "```" in summary:
                summary = summary.split("```")[0]
            return summary
        else:
            return "_Summary generation failed_"
    
    except Exception as e:
        print(f"Failed to generate narrative summary: {e}")
        return "_Summary generation error_"


if __name__ == "__main__":
    # Test with sample daily log
    sample_log = """# 2026-01-28

## Sessions

### Session Test
User reported critical bug in payment processing. Dashboard loading very slow (5+ seconds).
Made decision to use Python for backend rewrite. User prefers email over SMS notifications.
Fixed Redis connection errors by restarting service.

## Events
- Completed dashboard optimization
- Started backend rewrite planning
"""
    
    print("Testing memory extraction...")
    memories = extract_atomic_memories(sample_log)
    
    print(f"\nExtracted {len(memories)} memories:")
    for mem in memories:
        print(f"[{mem['importance']}] {mem['content'][:80]}...")
    
    if memories:
        print("\nNarrative summary:")
        print(generate_narrative_summary(memories))
