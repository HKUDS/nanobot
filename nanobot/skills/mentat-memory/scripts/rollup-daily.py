#!/usr/bin/env python3
"""
Daily → Weekly Rollup (Enhanced with Structured Memory Extraction)
Run at end of day (23:59) to distill today's daily log into this week's summary

Phase 1 Enhancement: Extract atomic memories to structured memory bank
while maintaining human-readable narrative summaries in weekly files.
"""

import json
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from memory_config import MEMORY_CONFIG
from memory_extraction import extract_atomic_memories, append_to_memory_bank, generate_narrative_summary

WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"
MEMORY_BANK = Path(MEMORY_CONFIG["MEMORY_BANK_PATH"])


def get_week_number(date):
    """Get ISO week number (YYYY-Wnn format)"""
    return date.strftime("%Y-W%V")


def summarize_with_llm(content, level="daily"):
    """Use agent to generate summary"""
    prompts = {
        "daily": """Summarize this daily log in 3-5 bullet points. Focus on:
- Key events and accomplishments
- Important decisions made
- Patterns or insights noticed
- Context worth remembering

Be concise but capture the essence. Write in past tense.

DAILY LOG:
""",
        "weekly": """Synthesize these daily summaries into a weekly overview. Extract:
- Major themes and patterns for the week
- Progress on ongoing projects
- Key decisions or pivots
- Lessons learned

Keep it under 200 words. Write cohesively, not as bullet points.

DAILY SUMMARIES:
""",
        "monthly": """Extract the monthly trajectory from these weekly summaries:
- What were the major themes this month?
- What progress was made on key projects?
- What changed or evolved?
- What's worth remembering long-term?

Keep it under 300 words. Focus on signal over noise.

WEEKLY SUMMARIES:
"""
    }
    
    prompt = prompts.get(level, prompts["daily"]) + content
    
    try:
        # Invoke agent directly (not sessions spawn)
        result = subprocess.run(
            ["clawdbot", "agent", "--agent", "main", "--message", prompt, "--json"],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            # Parse JSON response and extract text
            try:
                response = json.loads(result.stdout)
                # Extract text from clawdbot agent JSON response
                if isinstance(response, dict):
                    # Navigate: response -> result -> payloads -> [0] -> text
                    if "result" in response and "payloads" in response["result"]:
                        payloads = response["result"]["payloads"]
                        if payloads and len(payloads) > 0:
                            summary = payloads[0].get("text", "")
                            if summary:
                                return summary.strip()
                    # Fallback: try common keys
                    summary = response.get("text", response.get("content", ""))
                    if summary:
                        return summary.strip()
                # If all else fails, return the JSON as string (for debugging)
                return f"_JSON parsing failed. Response: {str(response)[:200]}_"
            except json.JSONDecodeError:
                # Fallback: use stdout directly
                return result.stdout.strip()
        else:
            print(f"Warning: LLM summarization failed: {result.stderr}")
            return f"_Summarization failed. See full log in daily file._\n"
    
    except Exception as e:
        print(f"Error during summarization: {e}")
        return f"_Summarization error: {e}_\n"


def rollup_daily_to_weekly():
    """Read today's daily, append summary to this week's weekly
    
    Enhanced with Phase 1 structured memory extraction:
    1. Extract atomic memories with importance scoring
    2. Store in structured memory bank (JSONL)
    3. Generate narrative summary for weekly (backward compatibility)
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
    
    # Phase 1 Enhancement: Extract structured memories
    if MEMORY_CONFIG["ENABLE_STRUCTURED_EXTRACTION"]:
        print(f"Extracting atomic memories from {daily_file.name}...")
        memories = extract_atomic_memories(daily_content)
        
        if memories:
            # Append to memory bank
            append_to_memory_bank(memories, MEMORY_BANK)
            
            # Generate narrative summary from structured memories
            print("Generating narrative summary for weekly...")
            summary_content = generate_narrative_summary(memories)
        else:
            print(f"No significant memories extracted (all importance < {MEMORY_CONFIG['MIN_IMPORTANCE_THRESHOLD']})")
            # Fallback to old LLM summarization if no structured memories
            summary_content = summarize_with_llm(daily_content, level="daily")
    else:
        # Legacy path: direct LLM summarization
        print(f"Generating summary for {daily_file.name}...")
        summary_content = summarize_with_llm(daily_content, level="daily")
    
    summary = f"\n## {today.strftime('%A, %B %d')}\n"
    summary += summary_content + "\n"
    
    # Append to weekly
    weekly_file.parent.mkdir(parents=True, exist_ok=True)
    
    if not weekly_file.exists():
        # Create weekly file
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


def cleanup_embedding_cache():
    """
    Clean up unsummarized session embedding caches for sessions that have been summarized.
    
    Called at end of day to free up space and prevent stale caches.
    """
    import json
    from pathlib import Path
    
    cache_dir = Path(".unsummarized-embeddings")
    if not cache_dir.exists():
        return
    
    state_file = Path("memory/diary/2026/.state.json")
    if not state_file.exists():
        return
    
    try:
        with open(state_file) as f:
            state = json.load(f)
            last_summarized = state.get('lastSummarizedSessionId')
        
        if not last_summarized:
            return
        
        # Get timestamp of last summarized session
        sessions_dir = Path.home() / ".clawdbot/agents/main/sessions"
        last_summarized_file = sessions_dir / f"{last_summarized}.jsonl"
        
        if not last_summarized_file.exists():
            return
        
        with open(last_summarized_file) as f:
            first_line = f.readline()
            session_meta = json.loads(first_line)
            timestamp = session_meta.get('timestamp')
            if not timestamp:
                return
            
            from datetime import datetime
            from zoneinfo import ZoneInfo
            last_summarized_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # Delete caches for sessions before or equal to last_summarized_time
        deleted = 0
        for cache_file in cache_dir.glob("*.json"):
            session_id = cache_file.stem
            session_file = sessions_dir / f"{session_id}.jsonl"
            
            if not session_file.exists():
                # Session doesn't exist anymore, clean up cache
                cache_file.unlink()
                deleted += 1
                continue
            
            try:
                with open(session_file) as f:
                    first_line = f.readline()
                    session_meta = json.loads(first_line)
                    timestamp = session_meta.get('timestamp')
                    if timestamp:
                        session_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        if session_time <= last_summarized_time:
                            cache_file.unlink()
                            deleted += 1
            except:
                continue
        
        if deleted > 0:
            print(f"✅ Cleaned up {deleted} embedding cache(s) for summarized sessions")
    
    except Exception as e:
        print(f"Warning: Error during embedding cache cleanup: {e}")


if __name__ == "__main__":
    rollup_daily_to_weekly()
    cleanup_embedding_cache()
