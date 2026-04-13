# task +comment

> **Prerequisites:** Please read `../lark-shared/SKILL.md` to understand authentication, global parameters, and security rules.

Add a comment to an existing task.

## Recommended Commands

```bash
# Add a comment
lark-cli task +comment --task-id "<task_guid>" --content "Looks good!"
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--task-id <guid>` | Yes | The task GUID to comment on. For Feishu task applinks, use the `guid` query parameter, not the `suite_entity_num` / display task ID like `t104121`. |
| `--content <text>` | Yes | The text content of the comment. |

## Workflow

1. Confirm the task and comment content.
2. Execute `lark-cli task +comment --task-id "..." --content "..."`
3. Report success and comment ID.

> [!CAUTION]
> This is a **Write Operation** -- You must confirm the user's intent before executing.
