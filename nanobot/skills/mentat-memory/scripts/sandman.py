#!/usr/bin/env python3
"""
Sandman - Overnight Analysis & Optimization System
Runs background tasks with dedicated budget and Claude-powered intelligence.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import requests

# Configuration
SANDMAN_NIGHTLY_BUDGET = 5.00  # Sandman's dedicated $5/night (separate from daily spend)
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
WORKSPACE = Path('/home/deva/shared')
STATE_FILE = WORKSPACE / 'memory/.sandman-state.json'

# Task definitions with estimated costs and models
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
        'id': 'memory_consistency',
        'name': 'Check memory system consistency',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 0.70,
        'priority': 3,
        'prompt': '''Review MEMORY.md and recent diary entries for:
1. Contradictions or outdated information
2. Missing cross-references
3. Information that should be in sticky-notes
4. Gaps in documentation

Output specific recommendations for fixes.'''
    },
    {
        'id': 'project_status',
        'name': 'Update project status summaries',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 0.60,
        'priority': 4,
        'prompt': '''Based on recent diary entries, update the status of active projects:
- PsiSurferLab
- Kascade Wilds
- TulpaTalk
- Air Quality Systems

For each: current status, recent progress, blockers, next steps.'''
    },
    {
        'id': 'self_analysis',
        'name': 'Analyze own performance',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 0.80,
        'priority': 5,
        'prompt': '''Review recent sessions and identify:
1. Where I (Deva) failed to follow instructions
2. Token waste or inefficient tool use
3. Missed context or opportunities
4. Areas for improvement

Be brutally honest. Output specific examples and fixes.'''
    },
    {
        'id': 'optimization_proposals',
        'name': 'Propose workflow optimizations',
        'model': 'openrouter/anthropic/claude-sonnet-4.5',
        'estimated_cost': 1.00,
        'priority': 6,
        'prompt': '''Based on all patterns detected, propose 3-5 specific optimizations to:
1. Workflow efficiency
2. Memory system improvements
3. Automation opportunities
4. Cost reduction strategies

Include implementation steps for each.'''
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


def run_task(task, budget_remaining):
    """Run a single task via background subagent."""
    if task['estimated_cost'] > budget_remaining:
        print(f"⏭️  Skipping {task['name']} (${task['estimated_cost']:.2f} > ${budget_remaining:.2f} remaining)")
        return None
    
    print(f"🔄 Running: {task['name']} (est. ${task['estimated_cost']:.2f})")
    
    # Build task prompt with context
    today = datetime.now().strftime('%Y-%m-%d')
    output_file = f"memory/sandman/{today}-{task['id']}.md"
    
    task_prompt = f"""SANDMAN OVERNIGHT TASK: {task['name']}
Date: {today}
Budget: ${task['estimated_cost']:.2f} allocated

{task['prompt']}

OUTPUT FORMAT:
Write your analysis to a file at: {output_file}

Use the `write` tool to create the file with:
- Timestamp header
- Analysis findings
- Actionable recommendations
- Any warnings or concerns

Format as markdown for readability.

IMPORTANT: You MUST write the file before completing. Verify it was created successfully.
"""
    
    try:
        # Create output directory
        output_dir = WORKSPACE / 'memory/sandman'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Spawn subagent with --cleanup keep so we can verify output
        result = subprocess.run(
            [
                'clawdbot', 'sessions', 'spawn',
                '--task', task_prompt,
                '--agent', 'main',
                '--timeout', '600',
                '--cleanup', 'keep',  # Keep session to verify completion
                '--label', f"sandman-{task['id']}"
            ],
            capture_output=True,
            text=True,
            timeout=660,  # 11 min (task timeout + buffer)
            cwd=str(WORKSPACE)
        )
        
        if result.returncode == 0:
            # Verify output file was created
            output_path = WORKSPACE / output_file
            if output_path.exists():
                print(f"✅ Completed: {task['name']} (output verified)")
                return {'task_id': task['id'], 'success': True, 'output_file': output_file}
            else:
                print(f"⚠️  Task ran but output file missing: {output_file}")
                return {'task_id': task['id'], 'success': False, 'error': 'Output file not created'}
        else:
            print(f"❌ Failed: {task['name']}")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
            return {'task_id': task['id'], 'success': False, 'error': result.stderr}
    
    except Exception as e:
        print(f"❌ Error running {task['name']}: {e}")
        return {'task_id': task['id'], 'success': False, 'error': str(e)}


def main():
    """Main sandman execution."""
    print("🌙 Sandman starting...")
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
    
    # Load state
    state = load_state()
    state['last_run'] = datetime.now().isoformat()
    
    # Sort tasks by priority
    sorted_tasks = sorted(TASKS, key=lambda t: t['priority'])
    
    # Run tasks until budget exhausted
    budget_remaining = budget_info['remaining']
    results = []
    
    for task in sorted_tasks:
        if budget_remaining <= 0:
            print("💰 Budget exhausted. Stopping task execution.")
            break
        
        result = run_task(task, budget_remaining)
        if result and result['success']:
            budget_remaining -= task['estimated_cost']
            results.append(result)
            state['completed_tasks'].append({
                'date': datetime.now().isoformat(),
                'task_id': task['id'],
                'cost': task['estimated_cost']
            })
    
    # Update state with spend
    spent_tonight = budget_info['remaining'] - budget_remaining
    state['sandman_daily_spend'] = budget_info['sandman_spent_today'] + spent_tonight
    state['total_spent'] = state.get('total_spent', 0) + spent_tonight
    save_state(state)
    
    # Clean up old sandman sessions (keep only last 3 days)
    try:
        cutoff_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        subprocess.run(
            ['clawdbot', 'sessions', 'list', '--json'],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(WORKSPACE)
        )
        # Note: Would need to parse JSON and delete old sandman-* labeled sessions
        # Skipping for now - manual cleanup acceptable
    except Exception as e:
        print(f"⚠️  Session cleanup failed: {e}")
    
    # Summary
    print(f"\n📊 Sandman Summary:")
    print(f"Tasks completed: {len(results)}/{len(TASKS)}")
    print(f"Spent tonight: ${spent_tonight:.2f}")
    print(f"Sandman daily total: ${state['sandman_daily_spend']:.2f}")
    print(f"Sandman remaining: ${budget_remaining:.2f}")
    print("🌙 Sandman complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
