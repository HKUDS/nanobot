# Feature: Cursor and GitHub CLI API keys for ExecTool subprocesses
Branch: feat/cursor-gh-variables
Last updated: 2025-02-27

## Summary
Adds CursorConfig and GhConfig to schema. Injects GH_TOKEN and CURSOR_API_KEY into os.environ at process startup (gateway, agent, cron run); ExecTool subprocesses inherit them. Matches how env vars are typically used: set once in parent, inherited by children. Same pattern as web search and LLM keys - minimal code changes.

## Files Touched
| File | Purpose |
|------|---------|
| nanobot/config/schema.py | Add CursorConfig and GhConfig classes; add cursor and gh to ToolsConfig |
| nanobot/cli/commands.py | Add _inject_cli_env(config); call after load_config in gateway, agent, cron run; add Cursor CLI and gh CLI status to `nanobot status` |

## Purpose
Tools that run in subprocesses (e.g. ExecTool spawning cursor or gh) need CURSOR_API_KEY and GH_TOKEN in the environment. Keys are injected into os.environ at process entry point; ExecTool passes env=None so subprocesses inherit. No changes to AgentLoop, ExecTool, or SubagentManager.

## Fixes / Improves
- Fixes: ExecTool subprocesses (cursor, gh) lacking API keys when invoked by the agent
- Improves: Status command shows Cursor/gh config state

## Conflict Resolution
When merging upstream into orghi-main, for each file that may conflict:

- **nanobot/config/schema.py**: If upstream adds new config classes or ToolsConfig fields, merge theirs and re-add cursor/gh. Our additions are CursorConfig, GhConfig, and the cursor/gh entries in ToolsConfig. Keep our additions; merge any upstream changes to surrounding schema.
- **nanobot/cli/commands.py**: Add _inject_cli_env(config) helper; call it after load_config in gateway, agent, cron run. For status(), add our Cursor CLI and gh CLI lines after upstream's provider status block.

## Worst Case: Accept Upstream, Rebuild
If conflicts are unresolvable or we reset to upstream:
1. Accept all upstream changes for the conflicted files.
2. Rebuild:
   - In schema.py: Add CursorConfig and GhConfig classes; add `cursor` and `gh` to ToolsConfig.
   - In commands.py: Add _inject_cli_env(config); call after load_config in gateway, agent, cron run; add status output for Cursor CLI and gh CLI.
3. Re-run tests: `uv run pytest` and `uv run pytest tests/orghi -v` if applicable.
