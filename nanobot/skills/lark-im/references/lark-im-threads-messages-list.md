# im +threads-messages-list

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Fetch the reply message list inside a thread. When `im +chat-messages-list` returns messages that include a `thread_id` field, use this command to inspect all replies in that thread.

This skill maps to the shortcut: `lark-cli im +threads-messages-list` (internally calls `GET /open-apis/im/v1/messages` with `container_id_type=thread` to fetch thread messages).

## Commands

```bash
# Get thread replies (ascending by time by default, table output)
lark-cli im +threads-messages-list --thread omt_xxx

# Reverse chronological order (latest first)
lark-cli im +threads-messages-list --thread omt_xxx --sort desc

# Control page size
lark-cli im +threads-messages-list --thread omt_xxx --page-size 20

# Pagination
lark-cli im +threads-messages-list --thread omt_xxx --page-token <PAGE_TOKEN>

# Output format options
lark-cli im +threads-messages-list --thread omt_xxx --format pretty
lark-cli im +threads-messages-list --thread omt_xxx --format table
lark-cli im +threads-messages-list --thread omt_xxx --format csv

# View as a bot
lark-cli im +threads-messages-list --thread omt_xxx --as bot

# Preview the request without executing it
lark-cli im +threads-messages-list --thread omt_xxx --dry-run
```

## Parameters

| Parameter | Required | Description |
|------|------|------|
| `--thread <id>` | Yes | Thread ID (`om_xxx` or `omt_xxx` format) |
| `--sort <order>` | No | Sort order: `asc` (default) / `desc` |
| `--page-size <n>` | No | Number of items per page (default 50, range 1-500) |
| `--page-token <token>` | No | Pagination token for the next page |
| `--format <fmt>` | No | Output format: `json` (default) / `pretty` / `table` / `ndjson` / `csv` |
| `--as <identity>` | No | Identity type: `user` (default) / `bot` |
| `--dry-run` | No | Print the request only, do not execute it |

## Core Constraints

### 1. Source of `thread_id`

`thread_id` (`omt_xxx` or `om_xxx`) comes from the `thread_id` field in results returned by `im +chat-messages-list` or `im +messages-search`. Do not guess a thread ID. Fetch messages first and use the returned value.

### 2. No time filtering support

Thread messages do not support `start_time` / `end_time` filtering because of Feishu API limitations. Use pagination and sort order to control the scope.

### 3. Pagination (`has_more` / `page_token`)

- When the result includes `has_more=true`, use `page_token` to fetch the next page
- If you need the complete thread, keep paginating; if you only need an overview, the first page is often enough

### 4. Recommended expansion strategy

| Scenario | Recommended Parameters |
|------|---------|
| Quickly inspect recent replies | `--sort desc --page-size 10` |
| Read the full thread in chronological order | `--sort asc --page-size 50`, then paginate as needed |
| Just confirm whether replies exist | `--sort desc --page-size 1` |

## Usage Scenarios

### Scenario 1: Expand a thread discovered in group messages

```bash
# Step 1: Fetch group messages and find one that contains thread_id
lark-cli im +chat-messages-list --chat-id oc_xxx

# Step 2: Extract thread_id from the JSON output and fetch thread replies
lark-cli im +threads-messages-list --thread omt_xxx
```

### Scenario 2: Paginate through a long thread

```bash
# First page
lark-cli im +threads-messages-list --thread omt_xxx

# If has_more=true is returned, continue with page_token
lark-cli im +threads-messages-list --thread omt_xxx --page-token <PAGE_TOKEN>
```

## Resource Rendering

Thread replies are rendered into human-readable text. Image messages appear as placeholders such as `[Image: img_xxx]`; resource binaries are **not** downloaded automatically.

Other resource types (files, audio, video) still need to be downloaded manually through `im +messages-resources-download`. See [lark-im-messages-resources-download](lark-im-messages-resources-download.md).

## Common Errors and Troubleshooting

| Symptom | Root Cause | Solution |
|---------|---------|---------|
| "Invalid thread ID format" | `thread_id` does not start with `om_` or `omt_` | Use a valid `om_xxx` or `omt_xxx` value |
| Empty thread result | Wrong thread_id or no replies in the thread | Confirm the thread_id came from `im +chat-messages-list` output |
| Permission denied | The user is not authorized or is not a conversation member | Make sure OAuth authorization is complete and the identity is a chat member |

## References

- [lark-im](../SKILL.md) - all message-related commands
- [lark-im-chat-messages-list](lark-im-chat-messages-list.md) - fetch conversation messages (source of `thread_id`)
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
