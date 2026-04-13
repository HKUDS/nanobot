# Group Chat Identity Rules

> Warning: The most common source of failure in group operations is choosing the wrong identity. Confirm the identity before performing the action.

Group-chat operations support both `--as user` (UAT user identity) and `--as bot` (TAT bot identity). Choosing the correct identity is critical for success.

## Basic Principles

- **If the user explicitly specifies an identity:** use exactly what the user requested (`--as user` or `--as bot`) without guessing.
- **If the user does not specify an identity:** infer the correct identity from context instead of relying on the default.

## Identity Selection by Operation

| Operation | Recommended Identity | Why |
|------|---------|-----------------------------------|
| Create group (`+chat-create`) | Depends on the scenario | Infer from context |
| Add members (member-management flow) | `--as user` | Bot visibility is limited and often fails when the target user is mutually invisible to the bot (232024) |
| Update group (`+chat-update`) | Owner identity | Permission changes require owner/admin privileges; owner transfer requires owner identity |

## Inferring the Owner

When an owner-level action is needed and the owner is unknown, infer in this order:

1. A bot created the group and `--owner` was **not** specified -> the owner is the bot (`--as bot`)
2. A bot created the group and `--owner ou_xxx` **was** specified -> the owner is that user (`--as user`)
3. A user created the group and `--owner` was **not** specified -> the owner is the current user (`--as user`)
4. Still unclear -> ask the user to confirm who owns the group before making owner-level changes

### When the Owner Is Neither the Current User Nor the Bot

If the query shows that the owner is a third-party user (`owner_id` is neither the currently authorized user nor the bot), the current identity does not have owner privileges. In that case:

- **Permission/setting changes:** if the bot is an admin of the group, `--as bot` can still perform admin-level operations such as renaming the group or changing permissions.
- **Owner-only actions such as owner transfer:** require the actual owner to complete UAT authorization via `lark-cli auth login`, then perform the action as that owner.
- Explain the limitation clearly to the user instead of retrying blindly.

## Common Pitfalls

### Inviting Members During Group Creation

If a bot creates a group and `--users` includes users who are mutually invisible to the bot, the entire request fails with 232043. Use two steps instead:

1. Create the group with the bot first, excluding invisible users: `lark-cli im +chat-create --name "Group Name"`
2. Add users later with a user-identity member-management flow

### Insufficient Privileges

- **232016 / 232002 / 232017:** the current identity is not the owner or an admin -> switch to the owner identity
- **232011:** the current user is not in the group -> use a group-member identity, or join the group first
- **232024:** the bot and the target user are mutually invisible -> switch to `--as user`

## References

- [lark-im](../SKILL.md) - all IM commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
