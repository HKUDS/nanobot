# Feature: Cursor and GitHub CLI API keys for ExecTool subprocesses
Branch: feat/cursor-gh-variables
Last updated: 2025-02-27

## Summary
Adds CursorConfig and GhConfig to schema, passes cursor_api_key and gh_api_key to AgentLoop (same pattern as brave_api_key), and sets os.environ in AgentLoop.__init__ so ExecTool subprocesses inherit CURSOR_API_KEY and GH_TOKEN.

## Files Touched
| File | Purpose |
|------|---------|
| nanobot/config/schema.py | Add CursorConfig and GhConfig classes; add cursor and gh to ToolsConfig |
| nanobot/agent/loop.py | Add cursor_api_key and gh_api_key params; set os.environ for CURSOR_API_KEY and GH_TOKEN so ExecTool subprocesses inherit |
| nanobot/cli/commands.py | Add _agent_loop_config_kwargs() helper; pass cursor_api_key and gh_api_key to AgentLoop; add Cursor CLI and gh CLI status to `nanobot status` |

## Purpose
Tools that run in subprocesses (e.g. ExecTool spawning cursor or gh) need CURSOR_API_KEY and GH_TOKEN in the environment. This change loads these keys from config and injects them into os.environ at AgentLoop startup, so any subprocess inherits them. Follows the same pattern as brave_api_key for WebSearchTool.

## Fixes / Improves
- Fixes: ExecTool subprocesses (cursor, gh) lacking API keys when invoked by the agent
- Improves: Centralized AgentLoop config via _agent_loop_config_kwargs; status command shows Cursor/gh config state

## Conflict Resolution
When merging upstream into orghi-main, for each file that may conflict:

- **nanobot/config/schema.py**: If upstream adds new config classes or ToolsConfig fields, merge theirs and re-add cursor/gh. Our additions are CursorConfig, GhConfig, and the cursor/gh entries in ToolsConfig. Keep our additions; merge any upstream changes to surrounding schema.
- **nanobot/agent/loop.py**: If upstream changes __init__ params or env handling, keep our cursor_api_key/gh_api_key params and the os.environ.setdefault loop. Merge upstream's other __init__ changes.
- **nanobot/cli/commands.py**: If upstream refactors AgentLoop creation or adds _agent_loop_config_kwargs, prefer merging their structure and ensuring cursor_api_key/gh_api_key are included. For status(), add our Cursor CLI and gh CLI lines after upstream's provider status block.

## Worst Case: Accept Upstream, Rebuild
If conflicts are unresolvable or we reset to upstream:
1. Accept all upstream changes for the conflicted files.
2. Rebuild:
   - In schema.py: Add CursorConfig and GhConfig classes; add `cursor` and `gh` to ToolsConfig.
   - In loop.py: Add cursor_api_key and gh_api_key to __init__; add `import os`; add loop that does `os.environ.setdefault("CURSOR_API_KEY", cursor_api_key)` and `os.environ.setdefault("GH_TOKEN", gh_api_key)` when value is truthy.
   - In commands.py: Ensure AgentLoop receives cursor_api_key and gh_api_key from config (via _agent_loop_config_kwargs or inline); add status output for Cursor CLI and gh CLI.
3. Re-run tests: `uv run pytest` and `uv run pytest tests/orghi -v` if applicable.
