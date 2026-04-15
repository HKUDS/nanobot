# task +create

> **Prerequisites:** Please read `../lark-shared/SKILL.md` to understand authentication, global parameters, and security rules.

Create a new task in Lark.

## Recommended Commands

```bash
# Create a task with all details
lark-cli task +create \
  --summary "Quarterly Sales Review" \
  --description "Review the sales performance for the last quarter." \
  --assignee "ou_xxx" \
  --due "2026-03-25" \
  --tasklist-id "https://applink.larkoffice.com/client/todo/task_list?guid=a4b00000-000-000-000-00000000036c"

# Create a simple task
lark-cli task +create \
  --summary "Buy milk"

# Preview the API call without executing
lark-cli task +create --summary "Test Task" --dry-run
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--summary <text>` | Yes | The title or summary of the task |
| `--description <text>` | No | Detailed description of the task |
| `--assignee <id>` | No | The `open_id` of the user to assign the task to (e.g., `ou_xxx`) |
| `--due <time>` | No | Due date. Supports ISO 8601, `YYYY-MM-DD`, relative time (e.g., `+2d`), or ms timestamp. `YYYY-MM-DD` and relative time will automatically set it as an all-day task. |
| `--tasklist-id <id>` | No | The GUID of the tasklist, or a full AppLink URL (the CLI will automatically extract the `guid` parameter from the URL). |
| `--idempotency-key <key>` | No | Client token to ensure idempotency of the request. |
| `--dry-run` | No | Preview the API call (JSON payload) without actually creating the task. |

## Workflow

1. Confirm with the user: task summary, due date, assignee, and tasklist if necessary.
   - **Crucial Rule for Assignee**: If the user explicitly or implicitly says "create a task for me" (给我创建一个任务), or "help me create a task" (帮我新建/创建一个任务), you MUST assign the task to the current logged-in user. You can get the current user's `open_id` by executing `lark-cli auth status --json` or `lark-cli contact +get-user` first, extracting the `userOpenId` or `open_id`, and then passing it to the `--assignee` parameter.
2. Execute `lark-cli task +create --summary "..." ...`
3. Report the result: task ID and summary.

> [!CAUTION]
> This is a **Write Operation** -- You must confirm the user's intent before executing.

## References

- [lark-task](../SKILL.md) -- All task commands
- [lark-shared](../../lark-shared/SKILL.md) -- Authentication and global parameters
