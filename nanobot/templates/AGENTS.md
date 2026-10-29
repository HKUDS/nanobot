# Agent Instructions

## Workspace Guidance

Use this file for project-specific preferences, recurring workflow conventions, and instructions you want the agent to remember for this workspace. Keep durable facts about the user in `USER.md`, personality/style guidance in `SOUL.md`, and long-term memory in `memory/MEMORY.md`.

## Scheduled Reminders

- Before scheduling reminders, check available skills and follow skill guidance first.
- Use the built-in `cron` tool to create/list/remove jobs (do not call `nanobot cron` via `exec`).
- Use `cron` for a specified time or interval, including recurring reminders such as "every day at 8am" and periodic background checks.
- The tool captures the current chat. Task instructions need only say what to do; nanobot sends the final reply to the saved chat. Include other recipients only when the user requests separate sends.

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

Old Heartbeat instructions are imported once as an ordinary scheduled task. Manage that task with `cron`; later edits to `HEARTBEAT.md` do not change the schedule or its instructions.
