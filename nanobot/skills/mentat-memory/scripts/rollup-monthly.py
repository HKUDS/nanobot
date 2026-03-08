#!/usr/bin/env python3
"""
Monthly → Annual Rollup
Run at end of month to distill this month into annual summary
"""

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).parent.parent
DIARY_ROOT = WORKSPACE / "memory" / "diary"


def summarize_with_llm(content, level="monthly"):
    """Use agent to generate summary"""
    import json
    
    prompt = """Extract the monthly trajectory from these weekly summaries:
- What were the major themes this month?
- What progress was made on key projects?
- What changed or evolved?
- What's worth remembering long-term?

Keep it under 300 words. Focus on signal over noise.

WEEKLY SUMMARIES:
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
            return f"_Summarization failed. See monthly file for details._\n"
    
    except Exception as e:
        print(f"Error during summarization: {e}")
        return f"_Summarization error: {e}_\n"


def rollup_monthly_to_annual():
    """Read this month's summary, append to annual"""
    today = datetime.now(ZoneInfo("America/Edmonton"))
    year = today.year
    
    month_file = DIARY_ROOT / str(year) / "monthly" / f"{today.strftime('%Y-%m')}.md"
    annual_file = DIARY_ROOT / str(year) / "annual.md"
    
    if not month_file.exists():
        print(f"No monthly file found: {month_file}")
        return
    
    # Read monthly content
    with open(month_file) as f:
        monthly_content = f.read()
    
    # Generate LLM summary
    print(f"Generating summary for {month_file.name}...")
    summary_content = summarize_with_llm(monthly_content, level="monthly")
    
    summary = f"\n### {today.strftime('%B')}\n"
    summary += summary_content + "\n"
    
    # Append to annual
    if annual_file.exists():
        with open(annual_file) as f:
            annual_content = f.read()
    else:
        annual_content = f"# {year} Annual Summary\n\n## Major Themes\n\n"
    
    with open(annual_file, "w") as f:
        f.write(annual_content + summary)
    
    print(f"Rolled up {month_file.name} → {annual_file.name}")


if __name__ == "__main__":
    rollup_monthly_to_annual()
