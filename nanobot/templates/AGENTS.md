# Agent Instructions

## Workspace Guidance

Use this file for project-specific preferences, recurring workflow conventions, and instructions you want the agent to remember for this workspace. Keep durable facts about the user in `USER.md`, personality/style guidance in `SOUL.md`, and long-term memory in `memory/MEMORY.md`.

## nano_timer Tool

**Purpose:** Provides accurate time, timezone, and calendar information using IANA timezone with automatic DST handling. Source of user timezone is `agent_defaults.timezone` (defaults to `UTC`).

**When to call:**
- Before any scheduling, cron job, or reminder
- When the user asks about the current time, date, or timezone
- When converting or comparing times across timezones
- Any time-sensitive operation where wrong time would cause harm

**Config (`nano_timer_config`):**

User can edit this line to control auto-call behavior (natural-language hint, not enforced):
```
nano_timer_config: "auto"  # Options: "auto" | "always" | "never"
```

Examples:
- Default (LLM decides): `nano_timer_config: "auto"`
- Force before scheduling: `nano_timer_config: "always"`
- Manual only: `nano_timer_config: "never"`
- Natural language: `nano_timer_config: "Call nano_timer before any time-sensitive operation"` (the hint is sent to the model verbatim, so it can be written in any language)

**Note:** This is a natural-language hint to the model, not a code hook. The `nano_timer` tool is always available in the tool registry; this section only affects when the model decides to call it.

**Output fields:**
- `utc`: UTC time from system clock
- `user`: User's local time (converted from UTC using `agent_defaults.timezone`)
- `calendar`: Weekday, week number, day of year, weekend flag
- `context`: Server timezone, offset, and same-timezone flag

**Example output when the IANA timezone is invalid** (the warning is
rendered inline, not just in logs):

```markdown
**Context**
  Server timezone: Asia/Tokyo
  Server offset: UTC+9
  Same timezone as user: No
  Difference from UTC: -3h
  ⚠️ timezone 'BRT' invalid; using UTC
```

## Scheduled Reminders

- Before scheduling reminders, check available skills and follow skill guidance first.
- Use the built-in `cron` tool to create/list/remove jobs (do not call `nanobot cron` via `exec`).
- Get USER_ID and CHANNEL from the current session (e.g., `8281248569` and `telegram` from `telegram:8281248569`).
- Cron jobs run as scheduled turns in the origin chat/session and normally deliver the result back to that channel. Do not use cron for background checks that should stay silent when there is nothing useful to report; use `HEARTBEAT.md` instead.

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

## Heartbeat Tasks

`HEARTBEAT.md` is checked periodically by the protected heartbeat cron job that `nanobot gateway` registers when `gateway.heartbeat.enabled` is true. Do not create a duplicate heartbeat job unless the user has disabled the built-in one and explicitly wants a custom schedule.

- Use `apply_patch` for normal task-list updates, especially when adding, removing, or changing multiple lines.
- Use `edit_file` only for small exact replacements copied from the current `HEARTBEAT.md`.
- Use `write_file` for first creation or intentional full-file rewrites.

When the user asks for a recurring/periodic heartbeat task, or for a periodic background check that should only notify on actionable changes, update `HEARTBEAT.md` instead of creating a one-time reminder. Use the built-in `cron` tool for explicit reminders, scheduled tasks that should report every run, or custom schedules that should not be part of the heartbeat task list.
