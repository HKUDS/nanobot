
# event +subscribe

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Subscribe to Lark events via WebSocket long connection, outputting NDJSON to stdout. Supports compact (agent-friendly) format, regex-based routing, and file output.

**Identity / Risk:**
- **Identity**: bot-only — uses App ID + App Secret to establish the WebSocket connection. No user login needed (`lark-cli config init` is sufficient).
- **Risk**: read — this is a read-only subscription command. It receives events but does not modify any resources.

**Platform-side configuration** (must be done in the Lark Open Platform console):
1. Events & Callbacks → Subscription method → Select "Use long connection to receive events"
2. Add the events you need (e.g. `im.message.receive_v1`)
3. Enable the corresponding permissions (e.g. `im:message:receive_as_bot`)

## Commands

```bash
# Subscribe to all registered events (catch-all mode, 24 common event types)
lark-cli event +subscribe

# Subscribe to specific event types only
lark-cli event +subscribe --event-types im.message.receive_v1

# Subscribe to multiple event types
lark-cli event +subscribe --event-types im.message.receive_v1,calendar.calendar.event.changed_v4

# Client-side regex filter (applied after SDK receives events)
lark-cli event +subscribe --filter "^im\."

# Agent-friendly format (parse content, strip noise fields)
lark-cli event +subscribe --event-types im.message.receive_v1 --compact --quiet

# Pretty-print JSON output
lark-cli event +subscribe --json

# Write each event to a file
lark-cli event +subscribe --output-dir ./events

# Route events to different directories by regex
lark-cli event +subscribe \
  --route '^im\.message=dir:./im/' \
  --route '^contact\.=dir:./contacts/'

# Route IM events to files, other events to stdout
lark-cli event +subscribe --route '^im\.=dir:./im-events/'

# Preview configuration without connecting
lark-cli event +subscribe --dry-run
```

## Parameters

| Parameter | Required | Description |
|------|------|------|
| `--event-types <types>` | No | Comma-separated event types to register with the SDK dispatcher. Only these types will be received. Omit for catch-all mode (24 common types) |
| `--filter <regex>` | No | Client-side regex filter on event_type, applied after the SDK delivers events. Can be combined with `--event-types` |
| `--compact` | No | Agent-friendly output: flatten structure, extract human-readable content, strip noise fields (schema, token, tenant_key, app_id) |
| `--json` | No | Pretty-print JSON instead of NDJSON (one line per event) |
| `--output-dir <dir>` | No | Write each event as an individual file: `{type}_{id}_{ts}.json` |
| `--route <spec>` | No | Regex-based event routing. Format: `regex=dir:./path`. Repeatable. Unmatched events fall through to `--output-dir` or stdout |
| `--quiet` | No | Suppress stderr status messages |
| `--force` | No | Bypass single-instance lock. **UNSAFE**: the server splits events randomly across connections, each instance only receives a subset |
| `--dry-run` | No | Print configuration only, do not connect to WebSocket |

## Output Formats

### Default (raw NDJSON)

One event per line, all fields included:

```json
{"schema":"2.0","header":{"event_id":"xxx","event_type":"im.message.receive_v1","create_time":"1773491924409","app_id":"cli_xxx"},"event":{"message":{"chat_id":"oc_xxx","content":"{\"text\":\"Hello\"}","message_id":"om_xxx","message_type":"text"},"sender":{"sender_id":{"open_id":"ou_xxx"},"sender_type":"user"}}}
```

### `--compact` (agent-friendly)

Flattened key-value output with semantic fields. The exact fields depend on the event type and its processor.

**IM message events** (`im.message.receive_v1`) have deep compact processing:

```json
{"type":"im.message.receive_v1","id":"om_xxx","message_id":"om_xxx","chat_id":"oc_xxx","chat_type":"p2p","message_type":"text","content":"Hello","sender_id":"ou_xxx","create_time":"1773491924409","timestamp":"1773491924409"}
```

- `event.message.content` (double-encoded JSON like `"{\"text\":\"Hello\"}"`) is parsed and converted to human-readable text via convertlib → output as `content`
- `event.sender.sender_id.open_id` → flattened to `sender_id`
- `schema`, `token`, `tenant_key`, `app_id` stripped
- Supports all message types: text, post, image, file, card, etc.

**Other IM events** (reactions, chat member changes, chat updates) also have specialized compact processors with relevant semantic fields.

**Non-IM events** (contact, calendar, approval, task, drive, application) use the generic compact processor:
- Parses the event payload as a flat map
- Injects `type` (event_type), `event_id`, and `timestamp` from the event header
- All original event fields are preserved as-is

Agent pipelines should **always use `--compact --quiet`**.

## Catch-all Event Types

The following 24 event types are registered in catch-all mode (when `--event-types` is omitted):

### IM

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `im.message.receive_v1` | Receive message | `im:message:receive_as_bot` |
| `im.message.message_read_v1` | Message read | `im:message:receive_as_bot` |
| `im.message.reaction.created_v1` | Reaction added | `im:message:receive_as_bot` |
| `im.message.reaction.deleted_v1` | Reaction removed | `im:message:receive_as_bot` |
| `im.chat.member.bot.added_v1` | Bot added to chat | `im:chat:readonly` |
| `im.chat.member.bot.deleted_v1` | Bot removed from chat | `im:chat:readonly` |
| `im.chat.member.user.added_v1` | User added to chat | `im:chat:readonly` |
| `im.chat.member.user.withdrawn_v1` | User add withdrawn | `im:chat:readonly` |
| `im.chat.member.user.deleted_v1` | User removed from chat | `im:chat:readonly` |
| `im.chat.updated_v1` | Chat info updated | `im:chat:readonly` |
| `im.chat.disbanded_v1` | Chat disbanded | `im:chat:readonly` |

### Contact

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `contact.user.created_v3` | User created | `contact:user.base:readonly` |
| `contact.user.updated_v3` | User updated | `contact:user.base:readonly` |
| `contact.user.deleted_v3` | User deleted | `contact:user.base:readonly` |
| `contact.department.created_v3` | Department created | `contact:department.base:readonly` |
| `contact.department.updated_v3` | Department updated | `contact:department.base:readonly` |
| `contact.department.deleted_v3` | Department deleted | `contact:department.base:readonly` |

### Calendar

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `calendar.calendar.acl.created_v4` | Calendar ACL created | `calendar:calendar.acl:readonly` |
| `calendar.calendar.event.changed_v4` | Calendar event changed | `calendar:calendar:readonly` |

### Approval

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `approval.approval.updated` | Approval status updated | `approval:approval:readonly` |

### Application

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `application.application.visibility.added_v6` | App visibility added | `application:application.app_visibility:readonly` |

### Task

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `task.task.update_tenant_v1` | Task updated (tenant) | `task:task:readonly` |
| `task.task.comment_updated_v1` | Task comment updated | `task:task:readonly` |

### Drive

| Event Type | Description | Required Scope |
|-----------|-------------|---------------|
| `drive.notice.comment_add_v1` | Drive comment added | `drive:drive:readonly` |

See the full list at [Lark Event List](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-list).

## Agent Pipeline Examples

### Listen for messages and reply with Claude

```bash
lark-cli event +subscribe \
  --event-types im.message.receive_v1 --compact --quiet \
  | while IFS= read -r line; do
      content=$(echo "$line" | jq -r '.content // empty')
      message_id=$(echo "$line" | jq -r '.message_id // empty')
      [[ -z "$content" ]] && continue

      # Generate reply with Claude
      answer=$(claude -p "Reply concisely: $content" < /dev/null 2>/dev/null)

      # Reply as bot
      reply_data=$(jq -n --arg t "$answer" '{msg_type:"text",content:({text:$t}|tojson)}')
      lark-cli api POST "/open-apis/im/v1/messages/$message_id/reply" \
        --data "$reply_data" --as bot --format data
    done
```

### Listen for messages and log to a Lark document

```bash
lark-cli event +subscribe \
  --event-types im.message.receive_v1 --compact --quiet \
  | while IFS= read -r line; do
      content=$(echo "$line" | jq -r '.content // empty')
      [[ -z "$content" ]] && continue

      lark-cli docs +update --doc "DOC_URL" --mode append --markdown "- $content"
    done
```

## Notes

- **Events must be configured in the Open Platform console** — the CLI cannot dynamically subscribe to event types
- `--event-types` controls which types the SDK dispatcher registers for. Unregistered types are silently dropped even if the server sends them. Omitting this flag registers 24 common types (catch-all)
- `--filter` is a pure client-side regex filter applied after the SDK delivers events. It does not affect which events are registered
- `--force` bypasses the single-instance lock per app. Without it, only one `+subscribe` process is allowed per app to prevent the server from splitting events across connections
- WebSocket auto-reconnects on disconnection (SDK built-in)
- `Ctrl+C` gracefully shuts down and prints the total event count
- Reply to messages with `lark-cli api ... --as bot` — no user login needed

## References

- [lark-im](../../lark-im/SKILL.md) — Messaging commands
- [lark-doc-update](../../lark-doc/references/lark-doc-update.md) — Update Lark documents
- [lark-shared](../../lark-shared/SKILL.md) — Authentication and global parameters
