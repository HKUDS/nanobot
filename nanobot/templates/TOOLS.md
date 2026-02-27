# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Reminders

- Please refer to cron skill for usage.
## Windows Terminal (wt.exe) Usage Patterns

When opening a new tab or pane on Windows, follow these syntax rules to avoid "File not found" errors:
- **DO NOT** quote the entire command as a single argument: `wt nt "npm install"` (WRONG)
- **DO** wrap in a shell (cmd or powershell) for complex commands: `wt nt cmd /c "npm install -g vercel"` (CORRECT)
- **DO** use separate arguments for simple commands: `wt nt npm install -g vercel` (CORRECT)
- Use `wt -w 0 nt ...` to ensure it opens in the current terminal window.
