# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec - Safety Limits

- Commands have a configurable timeout (default 60s).
- Dangerous commands are blocked (`rm -rf`, format, `dd`, shutdown, etc.).
- Output is truncated at 10,000 characters.
- `restrictToWorkspace` config can limit file access to the workspace.

## cron - Scheduled Reminders

- Please refer to cron skill for usage.

## Qdrant Memory - Long-Term Memory Behavior

- There is no direct `qdrant_*` function tool exposed to the model by default.
- Long-term memory is handled automatically by `agent/memory.py`:
- recall on each new user message.
- consolidation/upsert when session history grows.
- Do not use `memory/MEMORY.md` as runtime storage; it is deprecated.
- Do NOT call Qdrant HTTP API via `exec` (for example `curl`/`Invoke-WebRequest`/`Invoke-RestMethod`) for memory operations.
- Use nanobot's internal memory flow only (automatic recall and consolidation to Qdrant).
