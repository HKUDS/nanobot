---
name: cron
description: Schedule reminders and recurring tasks.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Two Modes

1. **Reminder** - message is sent directly to user
2. **Task** - message is a task description, agent executes and sends result

## Examples

One-time reminder:
```
cron(action="add", message="Call the doctor", run_at="2024-12-25T09:00:00")
```

Recurring reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| in 2 hours | run_at: (calculate ISO datetime) |
| tomorrow at 9am | run_at: "2024-01-15T09:00:00" |
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
