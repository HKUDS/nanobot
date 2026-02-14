# Sandman Task Execution Instructions

When you find `.sandman-trigger.json` in the workspace, execute this workflow:

## 1. Load Configuration
```python
import json
from pathlib import Path
from datetime import datetime

trigger_file = Path('/home/deva/shared/.sandman-trigger.json')
tasks_file = Path('/home/deva/shared/scripts/sandman/tasks.json')

# Read trigger
with open(trigger_file) as f:
    trigger = json.load(f)

# Read tasks
with open(tasks_file) as f:
    tasks = json.load(f)
```

## 2. Execute Each Task
For each task in priority order:

1. Check if budget allows (task cost ≤ remaining budget)
2. Replace `{date}` in prompt with today's date (YYYY-MM-DD)
3. Spawn task using `sessions_spawn` tool:
   ```python
   sessions_spawn(
       task=task['prompt'],
       label=f"sandman-{task['id']}",
       cleanup="keep",
       runTimeoutSeconds=600
   )
   ```
4. Wait for completion announcement
5. Verify output file exists at the path specified in prompt
6. Update budget tracking

## 3. Update State
After all tasks complete:

```python
state_file = Path('/home/deva/shared/memory/.sandman-state.json')

# Load existing state
with open(state_file) as f:
    state = json.load(f)

# Update
state['last_run'] = datetime.now().isoformat()
state['sandman_daily_spend'] += total_spent
state['completed_tasks'].append({
    'date': datetime.now().isoformat(),
    'tasks_run': completed_task_ids,
    'cost': total_spent
})

# Save
with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
```

## 4. Clean Up
```python
trigger_file.unlink()  # Delete trigger file
```

## 5. Report Summary
Write summary to: `memory/sandman/{date}-EXECUTION-SUMMARY.md`

Include:
- Tasks completed
- Tasks skipped (with reasons)
- Total spend
- Any errors or warnings
- Links to output files
