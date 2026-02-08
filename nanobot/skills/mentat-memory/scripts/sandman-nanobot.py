#!/usr/bin/env python3
"""
Sandman - Overnight Analysis & Optimization System (NANOBOT VERSION)
Runs background tasks with dedicated budget and Claude-powered intelligence.

ADAPTED FOR NANOBOT:
- Uses spawn tool interface (not CLI commands)
- Simplified to 3 concurrent tasks (nanobot's lighter architecture)
- Outputs task instructions for agent to execute via spawn tool
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import requests

# Configuration
SANDMAN_NIGHTLY_BUDGET = 5.00  # Sandman's dedicated $5/night (separate from daily spend)
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
WORKSPACE = Path.home() / '.nanobot' / 'workspace'
STATE_FILE = WORKSPACE / 'memory/.sandman-state.json'

# Task definitions - REDUCED TO 3 for nanobot (simpler, parallel execution)
TASKS = [
    {
        'id': 'enforcement_check',
        'name': 'Memory Enforcement Analysis',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 0.90,
        'priority': 1,  # HIGHEST - audit compliance first
        'prompt': '''Review today's session transcripts against AGENTS.md and MEMORY.md.

Check for violations:
1. Did I execute load-context.py at session start as required?
2. Did I read files in the correct order (SOUL → USER → context → MEMORY)?
3. Did I skip reading MEMORY.md in group chats (security requirement)?
4. Did I write important decisions/context to diary files?
5. Did I use "mental notes" instead of writing to files?
6. Did I follow the documented workflows and conventions?
7. Did I miss any mandatory skill reads when tasks matched their descriptions?

Be brutally honest. Flag every violation with:
- What I did wrong
- What I should have done
- Impact/risk level (low/medium/high)

Output specific examples with timestamps/session IDs.'''
    },
    {
        'id': 'pattern_detection',
        'name': 'Detect patterns across recent sessions',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 1.00,
        'priority': 2,
        'prompt': '''Analyze the past 3 days of diary entries and identify:
1. Recurring topics or questions
2. Workflow friction points
3. Tools/models that worked well vs. poorly
4. Any emerging patterns in behavior or focus

Output a concise summary with actionable insights.'''
    },
    {
        'id': 'self_analysis',
        'name': 'Analyze own performance',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 0.80,
        'priority': 3,
        'prompt': '''Review recent sessions and identify:
1. Where I (Tiny-Deva) failed to follow instructions
2. Token waste or inefficient tool use
3. Missed context or opportunities
4. Areas for improvement

Be brutally honest. Output specific examples and fixes.'''
    }
]


def check_budget():
    """Check Sandman's dedicated spend and return remaining budget."""
    try:
        # Load state to get Sandman's spend today
        state = load_state()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Reset daily spend if it's a new day
        if state.get('last_budget_reset') != today:
            state['sandman_daily_spend'] = 0.0
            state['last_budget_reset'] = today
            save_state(state)
        
        sandman_spent_today = state.get('sandman_daily_spend', 0.0)
        
        # Also fetch total account spend for logging
        response = requests.get(
            'https://openrouter.ai/api/v1/auth/key',
            headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}'},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()['data']
        
        return {
            'sandman_spent_today': sandman_spent_today,
            'remaining': SANDMAN_NIGHTLY_BUDGET - sandman_spent_today,
            'account_daily_spend': data['usage_daily'],
            'total_weekly': data['usage_weekly'],
            'total_monthly': data['usage_monthly']
        }
    except Exception as e:
        print(f"Error checking budget: {e}", file=sys.stderr)
        return None


def load_state():
    """Load sandman state from previous runs."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        'last_run': None,
        'completed_tasks': [],
        'total_spent': 0,
        'sandman_daily_spend': 0.0,
        'last_budget_reset': None
    }


def save_state(state):
    """Save sandman state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def generate_spawn_instructions():
    """Generate task instructions for agent to spawn via tool interface.
    
    Returns JSON array of task configs for agent to execute.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    
    spawn_tasks = []
    for task in TASKS:
        output_file = f"memory/sandman/{today}-{task['id']}.md"
        
        task_prompt = f"""SANDMAN OVERNIGHT TASK: {task['name']}
Date: {today}
Budget: ${task['estimated_cost']:.2f} allocated

{task['prompt']}

OUTPUT FORMAT:
Write your analysis to: {output_file}

Use write_file tool with:
- Timestamp header
- Analysis findings
- Actionable recommendations
- Any warnings or concerns

Format as markdown for readability.

CRITICAL: You MUST write the file before completing. Verify it was created successfully.
"""
        
        spawn_tasks.append({
            'label': f"Sandman: {task['name']}",
            'task': task_prompt,
            'output_file': output_file,
            'estimated_cost': task['estimated_cost']
        })
    
    return spawn_tasks


def main():
    """Main sandman execution - outputs spawn instructions for agent."""
    print("🌙 Sandman (Nanobot) starting...")
    print(f"Sandman's dedicated budget: ${SANDMAN_NIGHTLY_BUDGET:.2f}/night")
    
    # Check budget
    budget_info = check_budget()
    if not budget_info:
        print("⚠️  Could not check budget. Aborting for safety.")
        return 1
    
    print(f"Account daily spend: ${budget_info['account_daily_spend']:.2f}")
    print(f"Sandman spent today: ${budget_info['sandman_spent_today']:.2f}")
    print(f"Sandman remaining: ${budget_info['remaining']:.2f}")
    
    if budget_info['remaining'] <= 0:
        print("⚠️  Sandman's daily budget already used. Skipping tasks.")
        return 0
    
    # Generate spawn instructions
    spawn_tasks = generate_spawn_instructions()
    
    print("\n📋 SPAWN INSTRUCTIONS (Execute these via spawn tool):")
    print("="*60)
    print(json.dumps(spawn_tasks, indent=2))
    print("="*60)
    
    print(f"\n✅ Generated {len(spawn_tasks)} task configs")
    print("⚠️  Agent must execute these via spawn tool and verify outputs")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
