---
name: cron
description: Schedule reminders, recurring tasks, and periodic checks.
---

# Cron

Use the `cron` tool for **all** scheduled work. This is the single system for reminders,
recurring tasks, and periodic checks. Never use HEARTBEAT.md for user-requested tasks.

## Two Kinds of Jobs

### 1. Reminder (static message)
The `message` is delivered directly to the user as-is.
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

### 2. Task (agent executes and reports)
The `message` is treated as a **prompt** — the agent executes it using all available tools
(email, web, exec, file, etc.) and delivers the result to the user.
```
cron(action="add", message="Check my emails and summarize any important ones", every_seconds=7200)
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report the count", every_seconds=600)
cron(action="add", message="Fetch the weather forecast for Vancouver and send me a summary", cron_expr="0 7 * * *", tz="America/Vancouver")
```

Both kinds run through the full agent loop, so tasks have access to all tools.
The difference is intent: a reminder is a fixed notification; a task requires the agent to
do work and report findings.

## Scheduling Options

### Recurring interval
```
cron(action="add", message="...", every_seconds=3600)   # every hour
```

### Cron expression (with optional timezone)
```
cron(action="add", message="...", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

### One-time (auto-deletes after execution)
```
cron(action="add", message="Remind me about the meeting", at="2026-03-10T14:30:00")
```

## Management
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every 2 hours | every_seconds: 7200 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 9am PT | cron_expr: "0 9 * * 1-5", tz: "America/Vancouver" |
| in 30 minutes | at: "<compute ISO datetime from now + 30 min>" |

## Common Patterns

| User request | message |
|--------------|---------|
| Check my emails periodically | "Check my emails and let me know about any important ones" |
| Monitor a GitHub repo | "Check github.com/user/repo for new issues and summarize" |
| Daily news summary | "Fetch top tech news headlines and send a brief summary" |
| Periodic system health | "Run 'df -h' and report if any disk is above 90% usage" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
| 9am Vancouver time daily | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| at a specific time | at: ISO datetime string (compute from current time) |

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.
