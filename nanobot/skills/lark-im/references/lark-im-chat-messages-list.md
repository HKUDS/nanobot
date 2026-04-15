# im +chat-messages-list

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Fetch the message list for a conversation. Supports both group chats and direct messages.

This skill maps to the shortcut: `lark-cli im +chat-messages-list` (internally calls `GET /open-apis/im/v1/messages`, and automatically resolves the p2p chat_id when needed).

## Commands

```bash
# Get group chat messages (json output by default)
lark-cli im +chat-messages-list --chat-id oc_xxx

# Get direct messages with a user (pass open_id and resolve p2p chat_id automatically)
lark-cli im +chat-messages-list --user-id ou_xxx

# Specify a time range (ISO 8601)
lark-cli im +chat-messages-list --chat-id oc_xxx --start "2026-03-10T00:00:00+08:00" --end "2026-03-11T00:00:00+08:00"

# Specify a time range (date only)
lark-cli im +chat-messages-list --chat-id oc_xxx --start 2026-03-10 --end 2026-03-11

# Control sort order and page size (max 50)
lark-cli im +chat-messages-list --chat-id oc_xxx --sort asc --page-size 20

# Pagination
lark-cli im +chat-messages-list --chat-id oc_xxx --page-token "xxx"

# JSON output
lark-cli im +chat-messages-list --chat-id oc_xxx --format json
```

## Parameters

| Parameter | Required | Description |
|------|------|------|
| `--chat-id <id>` | One of two | Specify the conversation by its chat_id directly (e.g., group chat `oc_xxx`) |
| `--user-id <id>` | One of two | Specify a DM conversation by the other user's open_id (`ou_xxx`); p2p chat_id is resolved automatically |
| `--start <time>` | No | Start time (ISO 8601 or date only) |
| `--end <time>` | No | End time (ISO 8601 or date only) |
| `--sort <order>` | No | Sort order: `asc` / `desc` (default `desc`) |
| `--page-size <n>` | No | Page size (default 50, max 50) |
| `--page-token <token>` | No | Pagination token |

> Rule: `--chat-id` and `--user-id` are mutually exclusive. You must provide exactly one of them.

## Resource Rendering

Messages are rendered into human-readable text for inspection. Image messages are shown as placeholders such as `[Image: img_xxx]`; files and videos are rendered with resource keys in the content. Resource binaries are **not** downloaded automatically by this command.

Use [lark-im-messages-resources-download](lark-im-messages-resources-download.md) when you need to download an image or file from a specific message.

| Resource Type | Marker in Content | Behavior |
|---------|-------------|------|
| Image | `[Image: img_xxx]` | Download manually with `im +messages-resources-download --type image` |
| File | `<file key="file_xxx" .../>` | Download manually with `im +messages-resources-download --type file` |
| Audio | `<audio key="file_xxx" .../>` | Download manually with `im +messages-resources-download --type file` |
| Video | `<video key="file_xxx" .../>` | Download manually with `im +messages-resources-download --type file` |

## Thread Expansion (`thread_id`)

In JSON output, a message may contain a `thread_id` (`omt_xxx`) field, which means the message has replies in a thread. Use [`im +threads-messages-list`](lark-im-threads-messages-list.md) to inspect replies in that thread:

```bash
lark-cli im +threads-messages-list --thread omt_xxx
```

| Scenario | Recommendation |
|------|------|
| You need context | Call `im +threads-messages-list --sort desc --page-size 10` for the discovered thread_id to inspect recent replies |
| The user asks for the "full discussion" | Use `im +threads-messages-list --sort asc --page-size 50`, then paginate if needed |
| You only need an overview | Skip thread expansion |

## Output Fields

| Field | Description |
|------|------|
| `messages` | Message array |
| `total` | Number of messages in the current page |
| `has_more` | Whether additional pages are available |
| `page_token` | Pagination token for the next page |

Each message contains:

| Field | Description |
|------|------|
| `message_id` | Message ID |
| `msg_type` | Message type: `text`, `image`, `file`, `interactive`, `post`, `audio`, `video`, `system`, etc. |
| `create_time` | Creation time |
| `sender` | Sender information (includes `name` for user senders) |
| `content` | Message content |
| `deleted` | Whether the message has been recalled (always present, `true` = recalled) |
| `updated` | Whether the message has been edited after sending |
| `mentions` | Array of @mentions in the message; each item contains `{id, key, name}`. Present only when the message contains @mentions |
| `thread_id` | Thread ID (`omt_xxx`) if the message has replies in a thread. Present only when replies exist |

## Pagination (`has_more` / `page_token`)

`im +chat-messages-list` returns `has_more` and `page_token` when more data is available. Use `--page-token` to continue:

```bash
lark-cli im +chat-messages-list --chat-id oc_xxx --page-token <PAGE_TOKEN>
```

You can also fall back to the generic API:

```bash
lark-cli api GET /open-apis/im/v1/messages \
  --params 'container_id_type=chat&container_id=oc_xxx&page_size=50&page_token=<PAGE_TOKEN>'
```

## Common Errors and Troubleshooting

| Symptom | Root Cause | Solution |
|---------|---------|---------|
| `specify --chat-id <chat_id> or --user-id <open_id>` | Neither `--chat-id` nor `--user-id` was provided | You must provide exactly one |
| `--chat-id and --user-id cannot be specified together` | Both parameters were provided | Use only one |
| `P2P chat not found for this user` | `--user-id` was used but no p2p chat exists for the current identity and that user | Confirm the target direct-message relationship exists for the current identity |
| `--start: invalid time format` | Invalid time format | Use ISO 8601 or date-only format such as `2026-03-10` |
| Permission denied | Message read permissions are missing | Ensure the app has `im:message:readonly` and `im:chat:read` enabled |

## AI Usage Guidance

1. **Resolving chat_id from a chat name:** When the user refers to a chat by name and you don't have the `chat_id`, use [`+chat-search`](lark-im-chat-search.md) first:
   ```bash
   # Find chat_id by name, then list messages
   lark-cli im +chat-search --query "<chat name keyword>" --format json
   lark-cli im +chat-messages-list --chat-id <chat_id>
   ```
   **Do not use `im chats search` or `im chats list` — always use the `+chat-search` shortcut.**
2. **Prefer `--chat-id` when available:** if the chat_id is already known, use it directly to avoid extra API calls.
3. **For direct messages:** use `--user-id` to resolve the p2p chat automatically instead of looking it up manually.
4. **For time ranges:** both ISO 8601 and date-only inputs are supported. Date-only is usually simpler.
5. **For full content:** table output truncates content. Use `--format json` when you need the complete message body.
6. **For sender info:** the command already resolves sender names, so you do not need a separate lookup.

## References

- [lark-im](../SKILL.md) - all IM commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
