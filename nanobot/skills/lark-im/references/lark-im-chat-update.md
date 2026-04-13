# im +chat-update

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Update a group's name or description. Supports both **TAT (bot)** and **UAT (user)** identity.

This skill maps to the shortcut: `lark-cli im +chat-update` (internally calls `PUT /open-apis/im/v1/chats/:chat_id`).

## Commands

```bash
# Update the group name
lark-cli im +chat-update --chat-id oc_xxx --name "New Group Name"

# Update the group description
lark-cli im +chat-update --chat-id oc_xxx --description "Updated group description"

# Update multiple fields at once
lark-cli im +chat-update --chat-id oc_xxx \
  --name "Q2 Project Team" \
  --description "Owns Q2 goal tracking"

# Preview the request without executing it
lark-cli im +chat-update --chat-id oc_xxx --name "Test" --dry-run
```

## Parameters

### Required

| Parameter | Description |
|------|------|
| `--chat-id <oc_xxx>` | Group ID |

### Optional Fields

| Parameter | Limits | Description |
|------|------|------|
| `--name <name>` | Max 60 characters | Group name |
| `--description <text>` | Max 100 characters | Group description |

### Global Parameters

| Parameter | Description |
|------|------|
| `--format json` | Output as JSON (default) |
| `--dry-run` | Preview the request without executing it |

## Usage Scenarios

### Scenario 1: Rename a group and update its description

```bash
lark-cli im +chat-update --chat-id oc_xxx \
  --name "Q2 Project Team" \
  --description "Owns Q2 goal tracking"
```

## Common Errors and Troubleshooting

| Symptom | Root Cause | Solution |
|---------|---------|---------|
| `invalid --chat-id: expected chat ID (oc_xxx)` | Invalid chat_id format | Use a valid `oc_xxx` chat ID |
| `--name exceeds the maximum of 60 characters` | Group name too long | Shorten the name to 60 characters or fewer |
| `--description exceeds the maximum of 100 characters` | Group description too long | Shorten the description to 100 characters or fewer |
| `at least one field must be specified to update` | No update field was provided | Specify at least one field to update |
| Permission denied (99991679) | Missing `im:chat:update` permission | Run `lark-cli auth login --scope "im:chat:update"` |
| Non-owner/admin cannot update (232016/232002/232017) | Current identity is not the owner/admin | Try switching identity with `--as bot` or `--as user` |
| Not in the group (232011) | The current user is not a member of the group | Use a member identity (`--as bot`) or join the group first |

## AI Usage Guidance

### Identity Selection

`+chat-update` supports both user and bot identity (`--as user` / `--as bot`).

Infer the group owner from context whenever possible (for example, if a bot just created the group, the owner is the bot) and use the matching identity directly. If ownership is unclear, query the group first and confirm `owner_id`.

Identity choice should follow [Group Chat Identity Rules](lark-im-chat-identity.md): if the user explicitly specifies an identity, use it directly; otherwise infer the owner identity from context.

## References

- [lark-im](../SKILL.md) - all IM commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
