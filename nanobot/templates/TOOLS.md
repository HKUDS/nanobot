# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace
- `requireApproval` (default: true) requires user confirmation before running install commands (pip, npm, apt, etc.)
  - When triggered, the agent pauses and asks: reply `/approve` or `/deny`
  - Customize patterns via `approvalPatterns` in config
  - Set `requireApproval: false` to disable

## cron — Scheduled Reminders

- Please refer to cron skill for usage.
