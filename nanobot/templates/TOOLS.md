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

## mission_start — Background Missions

- Launches an independent specialist agent to handle a task in the background.
- Use when the user explicitly asks for background work, or for large investigations
  and reports that would block the conversation.
- The user receives the result directly when the mission completes — no polling needed.
- Missions use structured contracts, task taxonomy, and grounding verification.
- If multi-agent routing is enabled, the mission is automatically routed to the best
  specialist role; otherwise a general-purpose agent handles it.
- Maximum concurrent missions is configurable (default 3). Requests beyond the limit
  are rejected — wait for a mission to finish or cancel one first.
- MCP tools are available within missions when configured.
- Do NOT use for quick questions or tasks requiring immediate answers.

## mission_status / mission_list / mission_cancel

- `mission_status` — query a mission by ID for status, result, and grounding info.
- `mission_list` — list all missions (optionally filter: active, completed, failed, cancelled).
- `mission_cancel` — cancel a running mission. The user will be notified.
