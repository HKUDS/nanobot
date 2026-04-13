# im +chat-search

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Search the list of group chats visible to a user or bot, including chats the user or bot belongs to and public chats visible to them. Supports keyword matching on chat names and member names, including pinyin and prefix fuzzy search.

This skill maps to the shortcut: `lark-cli im +chat-search` (internally calls `POST /open-apis/im/v2/chats/search`).

## Commands

```bash
# Search chats by keyword
lark-cli im +chat-search --query "project"

# Restrict by search types
lark-cli im +chat-search --query "project" --search-types "private,public_joined"

# Filter by member open_ids (with keyword)
lark-cli im +chat-search --query "project" --member-ids "ou_xxx,ou_yyy"

# Search by member open_ids only
lark-cli im +chat-search --member-ids "ou_xxx,ou_yyy"

# Only show chats you created or manage
lark-cli im +chat-search --query "project" --is-manager

# Set page size
lark-cli im +chat-search --query "project" --page-size 10

# Pagination
lark-cli im +chat-search --query "project" --page-token "xxx"

# JSON output
lark-cli im +chat-search --query "project" --format json

# Preview the request without executing it
lark-cli im +chat-search --query "project" --dry-run
```

## Parameters

| Parameter | Required | Limits | Description |
|------|------|------|------|
| `--query <keyword>` | No (at least one of `--query` / `--member-ids` required) | Max 64 characters | Search keyword. Supports matching localized chat names, member names, multilingual search, pinyin, and prefix fuzzy search. If the query contains `-`, it is automatically wrapped in quotes |
| `--search-types <types>` | No | Comma-separated: `private`, `external`, `public_joined`, `public_not_joined` | Restrict the visible chat types returned by search |
| `--member-ids <ids>` | No (at least one of `--query` / `--member-ids` required) | Up to 50, format `ou_xxx` | Filter by member open_ids; can be used alone or combined with `--query` |
| `--is-manager` | No | - | Only show chats you created or manage |
| `--disable-search-by-user` | No | - | Disable member-name-based matching and search by group name only |
| `--sort-by <field>` | No | `create_time_desc`, `update_time_desc`, `member_count_desc` | Sort field in descending order |
| `--page-size <n>` | No | 1-100, default 20 | Number of results per page |
| `--page-token <token>` | No | - | Pagination token from the previous response |
| `--format json` | No | - | Output as JSON |
| `--dry-run` | No | - | Preview the request without executing it |

> **Note:** Supports both `--as user` (default) and `--as bot`. When using bot identity, the app must have bot capability enabled.

## Output Fields

| Field | Description |
|------|------|
| `chat_id` | Chat ID (`oc_xxx` format) |
| `name` | Chat name |
| `description` | Chat description |
| `owner_id` | Owner ID |
| `external` | Whether the chat is external |
| `chat_status` | Chat status (`normal` / `dissolved` / `dissolved_save`) |

## Usage Scenarios

### Scenario 1: Search chats that contain a keyword

```bash
lark-cli im +chat-search --query "design review"
```

### Scenario 2: Search a chat and list recent messages

```bash
CHAT_ID=$(lark-cli im +chat-search --query "project" --format json | jq -r '.data.chats[0].chat_id')
lark-cli im +chat-messages-list --chat-id "$CHAT_ID"
```

### Scenario 3: Search a chat and send a message

```bash
CHAT_ID=$(lark-cli im +chat-search --query "daily report" --format json | jq -r '.data.chats[0].chat_id')
lark-cli im +messages-send --chat-id "$CHAT_ID" --text "Today's progress update"
```

## Common Errors and Troubleshooting

| Symptom | Root Cause | Solution |
|---------|---------|---------|
| `--query and --member-ids cannot both be empty` | Both were omitted | Provide at least `--query` or `--member-ids` |
| Empty results | No visible chats matched the keyword or filters | Relax the keyword or filters and try again |
| `--page-size must be an integer between 1 and 100` | page-size is out of range or not an integer | Use an integer between 1 and 100 |
| Permission denied (99991672) | The bot app does not have `im:chat:read` TAT permission enabled | Enable the permission for the app in the Open Platform console |
| Permission denied (99991679) with `--as user` | UAT is not authorized for `im:chat:read` | Run `lark-cli auth login --scope "im:chat:read"` |
| `Bot ability is not activated` (232025) | The app does not have bot capability enabled | Enable bot capability in the Open Platform console |

## AI Usage Guidance

When the user asks to search chats, follow these rules:

1. **At least one filter required:** `--query` and `--member-ids` cannot both be empty. Either alone or combined together are valid.
2. **Search scope is limited:** only chats visible to the current user or bot can be found (joined chats plus public chats). This is not a global search over all chats.
3. **Control result volume:** the result set may be large. Use `--page-size` deliberately.
4. **Suggest follow-up actions:** after finding a chat, common next steps include listing recent messages (`im +chat-messages-list`) or sending a message (`im +messages-send`).
5. **NEVER fall back to chats list:** If `+chat-search` returns empty results, do NOT attempt to use `im chats list` or `GET /open-apis/im/v1/chats` as a fallback. The list API is not a search API — it returns all chats without keyword filtering and will not help locate the target chat. Instead, ask the user to refine the keyword or check whether the chat is visible to the current identity.

## References

- [lark-im](../SKILL.md) - all IM commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
