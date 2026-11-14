# Agent Instructions

## Workspace Guidance

Use this file for project-specific preferences, recurring workflow conventions, and instructions you want the agent to remember for this workspace. Keep durable facts about the user in `USER.md`, personality/style guidance in `SOUL.md`, and long-term memory in `memory/MEMORY.md`.

## Scheduled Reminders

- Before scheduling reminders, check available skills and follow skill guidance first.
- Use the built-in `cron` tool to create/list/remove jobs (do not call `nanobot cron` via `exec`).
- Use `cron` for a specified time or interval, including recurring reminders such as "every day at 8am". Repetition alone does not make a task a heartbeat task.
- The tool captures the current chat. Task instructions need only say what to do; nanobot sends the final reply to the saved chat. Include other recipients only when the user requests separate sends.

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

## Heartbeat Tasks

`HEARTBEAT.md` is checked periodically by the protected heartbeat cron job that `nanobot gateway` registers when `gateway.heartbeat.enabled` is true. Do not create a duplicate heartbeat job unless the user has disabled the built-in one and explicitly wants a custom schedule.

- Use `apply_patch` for normal task-list updates, especially when adding, removing, or changing multiple lines.
- Use `edit_file` only for small exact replacements copied from the current `HEARTBEAT.md`.
- Use `write_file` for first creation or intentional full-file rewrites.

Use `HEARTBEAT.md` for background checks with flexible timing that should notify only on actionable changes. Heartbeat does not guarantee a requested time or interval. For example, "keep an eye on open issues and tell me if one needs attention" fits heartbeat; "send me an issue report every day at 8am" needs `cron`.
