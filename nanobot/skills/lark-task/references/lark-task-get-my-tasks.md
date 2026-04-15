# task +get-my-tasks

If the user query only specifies a task name (e.g., "Complete task Lobster No. 1"), use this command to list and search for the task by its summary.

> **Prerequisites:** Please read `../lark-shared/SKILL.md` to understand authentication, global parameters, and security rules.
> 
> **⚠️ Note:** This API must be called with a user identity. **Do NOT use an app identity, otherwise the call will fail.**
>
> **Output rendering note:**
> 1. If you need to present user fields (assignee, creator, etc.), do not only output the raw `id` (e.g. open_id). Also try to resolve and display the user's real name (e.g. via the contact skill) for readability.
> 2. When rendering timestamps (e.g. created time, due time), use the local timezone. Format is 2006-01-02 15:04:05

List tasks assigned to the current user, with support for filtering by completion status, creation time, and due date.
By default, the command will automatically paginate up to 20 times. Use `--page-all` to fetch more (up to 40 pages).

## Recommended Commands

```bash
# Search for a specific task by name
lark-cli task +get-my-tasks --query "Lobster No. 1"

# Get all my tasks (fetches up to 20 pages by default)
lark-cli task +get-my-tasks

# Get my incomplete tasks (fetches up to 20 pages by default)
lark-cli task +get-my-tasks --complete=false

# Fetch all my tasks (up to 40 pages)
lark-cli task +get-my-tasks --page-all

# Fetch up to 10 pages
lark-cli task +get-my-tasks --page-limit 10

# Resume from a known page token
lark-cli task +get-my-tasks --page-token "pt_xxx"
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--query <string>` | No | Search for tasks by summary. Returns exact matches if any; otherwise returns partial matches. |
| `--complete=<bool>` | No | Optional. If not provided, it fetches all tasks (both incomplete and completed). Set to `true` to fetch only completed tasks, or `false` for incomplete tasks. |
| `--created_at <string>` | No | Query tasks created after this time. Supports date: `YYYY-MM-DD`, relative: `-2d`, or ms timestamp. |
| `--due-start <string>` | No | Query tasks with a due date after this time. Supports date: `YYYY-MM-DD`, relative: `-2d`, or ms timestamp. |
| `--due-end <string>` | No | Query tasks with a due date before this time. Supports date: `YYYY-MM-DD`, relative: `-2d`, or ms timestamp. |
| `--page-all` | No | Automatically paginate through all pages (max 40). |
| `--page-limit <int>` | No | Max page limit (default 20). |
| `--page-token <string>` | No | Start from the specified page token (useful for resuming a previous query). |

## Workflow

1. Determine the filters based on the user's request.
2. Execute the command. The CLI will automatically loop up to the specified limit (default 20, or 40 with `--page-all`) to fetch records.
3. Show the results (ID, summary, due time, and created date).
