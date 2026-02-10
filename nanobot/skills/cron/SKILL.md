---
name: cron
description: Schedule reminders and recurring tasks (Hot Reload, Echo Mode).
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Two Modes

1. **Echo** (`type="echo"`) - DIRECT MESSAGE. Best for simple text reminders. FAST & CHEAP.
2. **Agent** (`type="agent"`) - AI TASK. Agent thinks/uses tools. Use only if logic is needed.

## Examples

### 1. Simple Reminders (Echo)
**"Remind me to drink water in 20 mins"**
```python
cron(action="add", type="echo", message="Drink water", cron_expr="in 20m")
```

**"Remind me to sleep at 11pm"**
```python
# Requires user's timezone!
cron(action="add", type="echo", message="Sleep time", cron_expr="0 23 * * *", timezone="<User_Timezone>")
```

### 2. AI Tasks (Agent)
**"Check weather every morning at 8am"**
```python
cron(action="add", type="agent", message="Check London weather and report", cron_expr="0 8 * * *", timezone="Europe/London")
```

### 3. Batch Schedule
**"Remind me to stretch every 2 hours and drink water every hour"**
```python
cron(action="add", batch=[
    {"message": "Stretch", "cron_expr": "in 2h", "type": "echo"},
    {"message": "Drink water", "cron_expr": "in 1h", "type": "echo"}
])
```

## Parameters

| Parameter | Description |
|-----------|-------------|
| `action` | `add`, `list`, `remove` |
| `type` | `echo` (default, direct msg) or `agent` (AI logic) |
| `message` | The reminder text or task instruction |
| `cron_expr` | Schedule: "in 10m" (relative), "0 9 * * *" (cron), or ISO timestamp |
| `timezone` | e.g. "Europe/London" (Required for cron/ISO if not UTC) |
| `batch` | List of jobs to add at once (atomic) |
