# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## Cron — Scheduled Reminders

Use `exec` to create scheduled reminders:

```bash
# Recurring: every day at 9am
nanobot cron add --name "morning" --message "Good morning!" --cron "0 9 * * *"

# With timezone (--tz only works with --cron)
nanobot cron add --name "standup" --message "Standup time!" --cron "0 10 * * 1-5" --tz "Asia/Shanghai"

# Recurring: every 2 hours
nanobot cron add --name "water" --message "Drink water!" --every 7200

# One-time: specific ISO time
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"

# Deliver to a specific channel/user
nanobot cron add --name "reminder" --message "Check email" --at "2025-01-31T09:00:00" --deliver --to "USER_ID" --channel "CHANNEL"

# Manage jobs
nanobot cron list
nanobot cron remove <job_id>
```
