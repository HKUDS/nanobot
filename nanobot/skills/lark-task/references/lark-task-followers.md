# task +followers

> **Prerequisites:** Please read `../lark-shared/SKILL.md` to understand authentication, global parameters, and security rules.

Manage task followers. Add or remove followers from an existing task.

## Recommended Commands

```bash
# Add a follower
lark-cli task +followers --task-id "<task_guid>" --add "ou_aaa"

# Remove a follower
lark-cli task +followers --task-id "<task_guid>" --remove "ou_aaa"
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--task-id <guid>` | Yes | The task GUID to modify. For Feishu task applinks, use the `guid` query parameter, not the `suite_entity_num` / display task ID like `t104121`. |
| `--add <ids>` | No | Comma-separated list of user `open_id`s to add as followers. |
| `--remove <ids>` | No | Comma-separated list of user `open_id`s to remove from followers. |

## Workflow

1. Confirm the task and followers to add/remove.
2. Execute the command.
3. Report success.

> [!CAUTION]
> This is a **Write Operation** -- You must confirm the user's intent before executing.
