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

## calendar — Unified Calendar

- Supported providers: `local`, `feishu`
- `feishu` reads the user's personal Feishu calendar via OAuth 2.0 user access token:
  - On first use it opens a browser for authorization and starts a local HTTP callback server
  - OAuth tokens are stored under `feishu.token` in `~/.nanobot/auth.json` and refreshed automatically
  - The auth file is shared across all calendar providers: `{"feishu": {"token": {...}}, ...}`
  - Required OAuth scopes: `calendar:calendar:readonly`, `calendar:calendar.event:create`, `calendar:calendar.event:update`, `calendar:calendar.event:delete`
  - App credentials come from the Feishu channel config (`appId` / `appSecret`) or env vars `NANOBOT_FEISHU_APP_ID` / `NANOBOT_FEISHU_APP_SECRET`
  - Optional env vars: `NANOBOT_FEISHU_REDIRECT_URI` (default: `http://localhost:9527/callback`), `NANOBOT_FEISHU_CALENDAR_ID` (default: `primary`), `NANOBOT_FEISHU_DOMAIN` (`feishu` or `lark`)
