# Feature: Cursor and GitHub CLI API keys for ExecTool subprocesses
Branch: feat/cursor-gh-variables
Last updated: 2025-02-27

## Summary
Adds CursorConfig and GhConfig to schema, passes cursor_api_key and gh_api_key to AgentLoop (same pattern as brave_api_key), and stores them on self for use by tools/subprocesses.

## Files Touched
| File | Purpose |
|------|---------|
| nanobot/config/schema.py | Add CursorConfig and GhConfig classes; add cursor and gh to ToolsConfig |
| nanobot/agent/loop.py | Add cursor_api_key and gh_api_key params; store on self.cursor_api_key and self.gh_api_key |
| nanobot/cli/commands.py | Pass cursor_api_key and gh_api_key to AgentLoop at each call site (gateway, agent, cron run); add Cursor CLI and gh CLI status to `nanobot status` |

## Purpose
Tools that run in subprocesses (e.g. ExecTool spawning cursor or gh) need CURSOR_API_KEY and GH_TOKEN in the environment. This change loads these keys from config and passes them to AgentLoop, which stores them on self for downstream use. Follows the same pattern as brave_api_key for WebSearchTool.

## Fixes / Improves
- Fixes: ExecTool subprocesses (cursor, gh) lacking API keys when invoked by the agent
- Improves: Status command shows Cursor/gh config state

## Conflict Resolution
When merging upstream into orghi-main, for each file that may conflict:

- **nanobot/config/schema.py**: If upstream adds new config classes or ToolsConfig fields, merge theirs and re-add cursor/gh. Our additions are CursorConfig, GhConfig, and the cursor/gh entries in ToolsConfig. Keep our additions; merge any upstream changes to surrounding schema.
- **nanobot/agent/loop.py**: If upstream changes __init__ params, keep our cursor_api_key/gh_api_key params and self.cursor_api_key/self.gh_api_key assignments. Merge upstream's other __init__ changes.
- **nanobot/cli/commands.py**: If upstream refactors AgentLoop creation, ensure cursor_api_key and gh_api_key are passed at each call site (gateway, agent, cron run). For status(), add our Cursor CLI and gh CLI lines after upstream's provider status block.

## Worst Case: Accept Upstream, Rebuild
If conflicts are unresolvable or we reset to upstream:
1. Accept all upstream changes for the conflicted files.
2. Rebuild:
   - In schema.py: Add CursorConfig and GhConfig classes; add `cursor` and `gh` to ToolsConfig.
   - In loop.py: Add cursor_api_key and gh_api_key to __init__; assign self.cursor_api_key and self.gh_api_key.
   - In commands.py: At each AgentLoop call site (gateway, agent, cron run), pass cursor_api_key=config.tools.cursor.api_key or None and gh_api_key=config.tools.gh.api_key or None; add status output for Cursor CLI and gh CLI.
3. Re-run tests: `uv run pytest` and `uv run pytest tests/orghi -v` if applicable.
