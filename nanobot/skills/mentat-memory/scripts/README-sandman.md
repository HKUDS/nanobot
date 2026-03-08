# Sandman - Overnight Analysis & Optimization System

**Budget-aware background R&D that runs while you sleep.**

## Overview

Sandman is an automated overnight system that uses scheduled downtime to analyze patterns, maintain consistency, and propose optimizations. It runs with strict budget controls to prevent runaway costs.

## Features

### 1. **Memory Enforcement Analysis** 🚨
**Priority: HIGHEST**
- Audits compliance with AGENTS.md and MEMORY.md requirements
- Checks if load-context.py ran at session start
- Verifies correct file reading order
- Ensures MEMORY.md wasn't leaked to group chats (security)
- Catches "mental notes" instead of writing to files
- Flags violations of documented workflows
- **Output:** Brutally honest violation report with risk levels

### 2. **Pattern Detection**
- Analyzes recent sessions for recurring topics
- Identifies workflow friction points  
- Tracks which tools/models work well vs. poorly
- Surfaces emerging behavioral patterns

### 3. **Memory Consistency**
- Cross-checks MEMORY.md with diary entries
- Detects contradictions or outdated information
- Suggests sticky-note extractions
- Identifies documentation gaps

### 4. **Project Status Tracking**
- Updates status for active projects
- Tracks recent progress and blockers
- Proposes next steps

### 5. **Self-Analysis**
- Reviews own performance (instruction compliance, tool use efficiency)
- Identifies token waste
- Documents mistakes to avoid repetition
- Brutally honest self-assessment

### 6. **Optimization Proposals**
- Proposes workflow improvements
- Suggests memory system enhancements
- Identifies automation opportunities
- Recommends cost reduction strategies

## Budget Control

**Dedicated budget:** $5/night **separate from your daily spend** (configurable in `scripts/sandman.py`)

Sandman gets its own budget pool that resets daily, independent of your interactive usage.

**Safety features:**
- Dedicated spend tracking (separate from account totals)
- Task-level cost estimation
- Graceful degradation when budget exhausted
- Real-time spend tracking
- State persistence across runs
- Automatic daily reset at midnight

**Powered by Claude Sonnet 4.5:**
All tasks use Claude for maximum intelligence and analysis quality (~$5 total/night for comprehensive insights)

## Schedule

**Cron:** Daily at 3:00 AM MST

**Location:** `scripts/sandman.py`

## Task Definitions

Tasks are defined in `TASKS` array in `sandman.py`:

```python
{
    'id': 'pattern_detection',
    'name': 'Detect patterns across recent sessions',
    'model': 'openrouter/google/gemini-2.5-flash',
    'estimated_cost': 0.50,
    'priority': 1,  # Higher = more important
    'prompt': '...'
}
```

**Priority system:**
- Tasks run in priority order (1 = highest)
- Lower-priority tasks skipped if budget exhausted
- Critical tasks (pattern detection, consistency) run first

## Output

**Location:** `memory/sandman/YYYY-MM-DD-{task_id}.md`

**State file:** `memory/.sandman-state.json`

Contains:
- Task results and analysis
- Timestamp and cost metadata
- Actionable recommendations

## Customization

### Adjust Budget

Edit `SANDMAN_NIGHTLY_BUDGET` in `scripts/sandman.py`:

```python
SANDMAN_NIGHTLY_BUDGET = 5.00  # Sandman's dedicated $5/night
```

### Add/Remove Tasks

Edit the `TASKS` array in `scripts/sandman.py`:

```python
TASKS = [
    {
        'id': 'your_task_id',
        'name': 'Human-readable task name',
        'model': 'openrouter/google/gemini-2.5-flash',
        'estimated_cost': 0.30,
        'priority': 3,
        'prompt': '''Your analysis prompt here'''
    },
    # ... more tasks
]
```

### Change Schedule

Use `clawdbot cron update`:

```bash
clawdbot cron update sandman-overnight-optimization --schedule "0 2 * * *"
```

## Monitoring

**Check state:**
```bash
cat memory/.sandman-state.json | jq
```

**View recent results:**
```bash
ls -lh memory/sandman/
```

**Check daily spend:**
```bash
curl -s https://openrouter.ai/api/v1/auth/key \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  | jq '.data.usage_daily'
```

## Manual Run

Test sandman outside of cron:

```bash
python3 scripts/sandman.py
```

**Note:** Respects the same budget limits.

## Safety & Limits

- **No external actions:** Sandman only reads/analyzes, never sends messages or runs destructive commands
- **Budget-first:** Checks spend before starting any work
- **Fail-safe:** If budget API is unreachable, sandman aborts (no blind spending)
- **Incremental:** Results saved per-task, so partial runs still produce value
- **State persistence:** Tracks completion history to avoid duplicate work

## Future Enhancements

Potential extensions:
- Anomaly detection (sleep schedule drift, unusual spending)
- Proactive reminders based on diary patterns
- Knowledge graph construction
- Cross-referencing with external data sources (calendar, email)
- Adaptive task prioritization based on recent user activity

---

**Last Updated:** 2026-01-29  
**Version:** 1.0.0  
**Author:** Deva (with Josiah)
