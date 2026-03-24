---
name: cron
description: Schedule reminders and recurring tasks with isolated or main session execution.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Session Modes

1. **Isolated** (default) - runs in a dedicated `cron:<id>` session. Fresh context each run, doesn't pollute main chat history. Best for background chores and noisy tasks.
2. **Main** - injects a system event into the heartbeat cycle. Uses full main-session context. Best when the agent needs conversational continuity.

## Delivery Modes

- **announce** (default for isolated) - deliver output directly to the target channel
- **webhook** - POST output to a URL
- **none** - no delivery (internal only)

## Examples

Isolated recurring task (default):
```
cron(action="add", message="Check GitHub stars and report", every_seconds=600)
```

Main session system event:
```
cron(action="add", message="Check calendar for upcoming events", cron_expr="*/30 * * * *", session="main", wake_mode="now")
```

One-time reminder (auto-deletes):
```
cron(action="add", message="Remind me about the meeting", at="2026-03-05T10:30:00")
```

Timezone-aware cron:
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver", session="isolated")
```

Update a job:
```
cron(action="update", job_id="abc123", message="New prompt text")
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
| 9am Vancouver time daily | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| at a specific time | at: ISO datetime string |

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.

## Retry Behavior

- Transient errors (network, timeout, rate limit, 5xx) are retried with exponential backoff: 30s, 1m, 5m, 15m, 60m
- Permanent errors (auth failures, config errors) disable the job immediately
- One-shot jobs retry up to 3 times on transient errors
- Successful runs reset the backoff counter

## CLI

```bash
nanobot cron list
nanobot cron add --name "Brief" --cron "0 7 * * *" --session isolated --message "..."
nanobot cron remove <job_id>
nanobot cron run <job_id>
nanobot cron runs --id <job_id>
nanobot cron edit <job_id> --message "New prompt"
```
