# task +update

> **Prerequisites:** Please read `../lark-shared/SKILL.md` to understand authentication, global parameters, and security rules.

Update an existing task in Lark.

## Recommended Commands

```bash
# Update task summary
lark-cli task +update --task-id "<task_guid>" --summary "New Summary"

# Update multiple tasks' due dates
lark-cli task +update --task-id "<task_guid>,<another_task_guid>" --due "+2d"

# Update with JSON data
lark-cli task +update --task-id "<task_guid>" --data '{"description": "New description"}'
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--task-id <guid>` | Yes | The task GUID to update. Comma-separated task GUIDs are supported for multiple tasks. For Feishu task applinks, use the `guid` query parameter, not the `suite_entity_num` / display task ID like `t104121`. |
| `--summary <text>` | No | New summary/title for the task. |
| `--description <text>` | No | New description for the task. |
| `--due <time>` | No | New due date (supports relative time). |
| `--data <json>` | No | JSON payload for fields to update. |

## Workflow

1. Confirm with the user the tasks to update and the fields.
2. Execute `lark-cli task +update --task-id "..." ...`
3. Report the successful updates.

> [!CAUTION]
> This is a **Write Operation** -- You must confirm the user's intent before executing.
