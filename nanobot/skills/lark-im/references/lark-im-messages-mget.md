# im +messages-mget

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Fetch message details in batch. Given a list of message IDs, this returns the full content for multiple messages in one call and automatically resolves sender names.

> **Supports both `--as user` (default) and `--as bot`.**

This skill maps to the shortcut: `lark-cli im +messages-mget` (internally calls `GET /open-apis/im/v1/messages/mget`).

## Commands

```bash
# Fetch a single message
lark-cli im +messages-mget --message-ids om_xxx

# Fetch multiple messages in batch (comma-separated)
lark-cli im +messages-mget --message-ids "om_aaa,om_bbb,om_ccc"

# JSON output
lark-cli im +messages-mget --message-ids "om_aaa,om_bbb" --format json

# Preview the request without executing it
lark-cli im +messages-mget --message-ids "om_aaa" --dry-run
```

## Parameters

| Parameter | Required | Limits | Description |
|------|------|------|------|
| `--message-ids <ids>` | Yes | At least one, max 50, `om_xxx` format, comma-separated | Message ID list |

## Output Fields

| Field | Description |
|------|------|
| `messages` | Message array |
| `total` | Number of messages returned |

Each message contains:

| Field | Description |
|------|------|
| `message_id` | Message ID |
| `msg_type` | Message type (`text`, `image`, `file`, etc.) |
| `create_time` | Creation time |
| `sender` | Sender information (includes `name`) |
| `content` | Message content |

## Usage Scenarios

### Scenario 1: Fetch the full content of a specific message

```bash
lark-cli im +messages-mget --message-ids om_xxx --format json
```

### Scenario 2: Fetch multiple messages in one batch

```bash
lark-cli im +messages-mget --message-ids "om_aaa,om_bbb,om_ccc"
```

### Scenario 3: Use together with the message list command

First get message IDs via `+chat-messages-list`, then fetch full content via `+messages-mget`:

```bash
# Get the message list
lark-cli im +chat-messages-list --chat-id oc_xxx --format json

# Fetch specific message details
lark-cli im +messages-mget --message-ids "om_aaa,om_bbb"
```

## Common Errors and Troubleshooting

| Symptom | Root Cause | Solution |
|---------|---------|---------|
| `--message-ids requires at least one message ID` | No message ID was provided | Provide at least one message ID |
| `invalid message ID: must start with om_` | Invalid message ID format | Message IDs must start with `om_` |
| Permission denied | Message read permission is missing | Ensure the app has `im:message:readonly` and `contact:user.base:readonly` enabled |
| Empty result | Message IDs do not exist or are not accessible | Verify the IDs and access permissions |

## AI Usage Guidance

1. **Use JSON for full content:** table output truncates content. Use `--format json` when the full body matters.
2. **Sender names are already enriched:** the command resolves sender names automatically, so no extra lookup is required.
3. **Images are rendered as placeholders:** image messages appear as placeholders such as `[Image: img_xxx]`. Use `+messages-resources-download` when you need the binary resource.
4. **Batching is more efficient:** fetching multiple IDs in one request is better than calling the API repeatedly.

## References

- [lark-im](../SKILL.md) - all IM commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
