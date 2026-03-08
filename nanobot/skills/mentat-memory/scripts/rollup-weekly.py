#!/usr/bin/env python3
"""
Weekly → Monthly Rollup
Run at end of week (Sunday 23:59) to distill this week into this month's summary
"""

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"


def summarize_with_llm(content, level="weekly"):
    """Use agent to generate summary"""
    import json
    
    prompt = """Synthesize these daily summaries into a weekly overview. Extract:
- Major themes and patterns for the week
- Progress on ongoing projects
- Key decisions or pivots
- Lessons learned

Keep it under 200 words. Write cohesively, not as bullet points.

DAILY SUMMARIES:
""" + content
    
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
            return f"_Summarization failed. See weekly file for details._\n"
    
    except Exception as e:
        print(f"Error during summarization: {e}")
        return f"_Summarization error: {e}_\n"


def rollup_weekly_to_monthly():
    """Read this week's summary, append to this month's monthly"""
    today = datetime.now(ZoneInfo("America/Edmonton"))
    year = today.year
    
    week_num = today.strftime("%Y-W%V")
    weekly_file = DIARY_ROOT / str(year) / "weekly" / f"{week_num}.md"
    
    month_file = DIARY_ROOT / str(year) / "monthly" / f"{today.strftime('%Y-%m')}.md"
    
    if not weekly_file.exists():
        print(f"No weekly file found: {weekly_file}")
        return
    
    # Read weekly content
    with open(weekly_file) as f:
        weekly_content = f.read()
    
    # Generate LLM summary
    print(f"Generating summary for {weekly_file.name}...")
    summary_content = summarize_with_llm(weekly_content, level="weekly")
    
    summary = f"\n## Week {week_num.split('-W')[1]}\n"
    summary += summary_content + "\n"
    
    # Append to monthly
    month_file.parent.mkdir(parents=True, exist_ok=True)
    
    if month_file.exists():
        with open(month_file) as f:
            monthly_content = f.read()
    else:
        monthly_content = f"# {today.strftime('%B %Y')}\n\n## Overview\n_To be populated by monthly rollup_\n\n## Weekly Summaries\n"
    
    with open(month_file, "w") as f:
        f.write(monthly_content + summary)
    
    print(f"Rolled up {weekly_file.name} → {month_file.name}")


if __name__ == "__main__":
    rollup_weekly_to_monthly()
