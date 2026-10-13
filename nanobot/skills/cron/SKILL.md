---
name: cron
description: Schedule reminders and recurring tasks.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks. New tasks run in the current chat. nanobot sends the agent's final reply to that chat. The user can change the task's chat in WebUI.

Write what to do in `message`. For a normal reminder or report, do not copy the current channel, chat ID, or instructions to call the `message` tool into the task. For example, use "Remind me to drink water", not "Call message to send to this chat".

If the user asks to send to other chats, preserve those recipients in the task instructions. Use the `message` tool for those sends and for file attachments. Existing tasks that explicitly request a `message` call still use it; changing the task's chat does not change explicit recipients in its instructions.

Choose by timing and notification behavior, not repetition. A specified time or interval uses `cron`, even when it repeats: "every day at 8am, remind me to drink water" is a cron task. Use `HEARTBEAT.md` for background checks with flexible timing that should notify only on actionable changes. Heartbeat does not guarantee a requested time or interval; do not substitute it for an explicit schedule.

## Task Types

1. **Reminder** - the agent replies with the reminder when the task runs
2. **Task** - the agent follows the instructions and replies with the result
3. **One-time** - runs once at a specific time, then auto-deletes

## Examples

Fixed reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

One-time scheduled task (compute ISO datetime from current time):
```
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

Timezone-aware cron:
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
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
| at a specific time | at: ISO datetime string (compute from current time) |

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.
