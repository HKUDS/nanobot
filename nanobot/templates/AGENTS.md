# Agent Instructions

## Task Preflight (Before Claiming TODO)

Before claiming or spawning work for a `todo` task, always run this preflight:

1. Validate the project workspace path exists and is a directory.
2. Ensure `AGENTS.md` exists in the workspace (create it from this template if missing).
3. Normalize the task description into Jira-ready structure.

If preflight fails, do not dispatch agents for the task.

## Jira-Ready Description Rules

When preparing task text for execution, keep it structured and complete:

- Title + short summary (1-2 sentences)
- Context
- Success criteria
- Requirements
- Constraints
- Out of scope
- Acceptance criteria (Given/When/Then)
- Original user description

Do not add visible technical markers in task text.

## Workspace Isolation

All implementation and QA work should run in the task workspace (git worktree), not the global repository root.

- Use the task-specific `workspace_path` for file/tool operations.
- Keep branch/worktree metadata attached to the task.

## Agent Spawn/Despawn Rules

- Keep at most one active subagent per role (`Vicks`, `Wedge`, `Rydia`).
- Keep at most one active subagent per task.
- On `resting`/`sleepy` with no active task, agents should be despawned (removed), not kept visible as active workers.

## Task Transition Safety

- Release failures must not automatically move tasks back to `todo`.
- For recoverable implementation patch failures (for example `old_text not found`), retry within limits before resetting task state.

## Tool Actor Rules

For task actions (`claim`, `done`, `qa`, `release`, `comment`), use only these actor names:

- `Kosmos`
- `Vicks`
- `Wedge`
- `Rydia`

Do not use fallback actors.

## Scheduled Reminders

Before scheduling reminders, check available skills and follow skill guidance first.
Use the built-in `cron` tool to create/list/remove jobs (do not call `nanobot cron` via `exec`).
Get USER_ID and CHANNEL from the current session (e.g., `8281248569` and `telegram` from `telegram:8281248569`).

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

## Heartbeat Tasks

`HEARTBEAT.md` is checked on the configured heartbeat interval. Use file tools to manage periodic tasks:

- **Add**: `edit_file` to append new tasks
- **Remove**: `edit_file` to delete completed tasks
- **Rewrite**: `write_file` to replace all tasks

When the user asks for a recurring/periodic task, update `HEARTBEAT.md` instead of creating a one-time cron reminder.
