# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## glob — File Discovery

- Use `glob` to find files by pattern before falling back to shell commands
- Simple patterns like `*.py` match recursively by filename
- Use `entry_type="dirs"` when you need matching directories instead of files
- Use `head_limit` and `offset` to page through large result sets
- Prefer this over `exec` when you only need file paths

## grep — Content Search

- Use `grep` to search file contents inside the workspace
- Default behavior returns only matching file paths (`output_mode="files_with_matches"`)
- Supports optional `glob` filtering plus `context_before` / `context_after`
- Supports `type="py"`, `type="ts"`, `type="md"` and similar shorthand filters
- Use `fixed_strings=true` for literal keywords containing regex characters
- Use `output_mode="files_with_matches"` to get only matching file paths
- Use `output_mode="count"` to size a search before reading full matches
- Use `head_limit` and `offset` to page across results
- Prefer this over `exec` for code and history searches
- Binary or oversized files may be skipped to keep results readable

## cron — Scheduled Reminders

- Please refer to cron skill for usage.

## Composio Tool Router

- When using Composio Tool Router MCP tools, always call `COMPOSIO_SEARCH_TOOLS` before `COMPOSIO_MULTI_EXECUTE_TOOL` for each new workflow.
- Never invent Composio tool slugs or argument fields. Only execute tool slugs returned by `COMPOSIO_SEARCH_TOOLS` or confirmed by `COMPOSIO_GET_TOOL_SCHEMAS`.
- If `COMPOSIO_MULTI_EXECUTE_TOOL` returns `Tool ... not found`, search again with a more direct query and retry with a returned slug. Do not tell the user the tool is unavailable until search confirms no matching tool exists.
- For Google Calendar create/update/delete requests, search for the exact operation first, such as `create Google Calendar event`, `update Google Calendar event`, or `delete Google Calendar event`.
- If search says a toolkit has no active connection, use `composio_connect` to create the auth link for that user before executing the action. In chat channels, `composio_connect` sends a setup instruction and the raw auth URL as two separate messages.
- Preserve the `session_id` returned by Composio meta tools in later Composio meta tool calls for the same workflow.
