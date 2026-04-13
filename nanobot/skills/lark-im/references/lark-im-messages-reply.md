# im +messages-reply

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Reply to a specific message. Supports both user identity (`--as user`) and bot identity (`--as bot`). Also supports thread replies.

This skill maps to the shortcut: `lark-cli im +messages-reply` (internally calls `POST /open-apis/im/v1/messages/:message_id/reply`).

## Safety Constraints

Replies sent by this tool are visible to other people. Before calling it, you **must** confirm with the user:

1. Which message to reply to
2. The reply content
3. Which identity to use (user or bot)

**Do not** send a reply without explicit user approval.

When using `--as bot`, the reply is sent in the app's name, so make sure the app has already been added to the target chat.

When using `--as user`, the reply is sent as the authorized end user and requires the `im:message.send_as_user` and `im:message` scopes.

## Choose The Right Content Flag

| Need | Recommended flag | Why |
|------|------|------|
| Reply with plain text exactly as written | `--text` | Wrapped directly to `{"text":"..."}` |
| Reply with simple Markdown and accept conversion | `--markdown` | Automatically converted to `post` JSON |
| Precisely control the reply payload | `--content` | You provide the exact JSON |
| Reply with media | `--image` / `--file` / `--video` / `--audio` | Shortcut uploads local files automatically |

### `--text` vs `--markdown`

- Use `--text` when the reply should remain plain text and you want exact control over line breaks, spacing, indentation, code samples, or literal Markdown characters.
- Use `--markdown` when you want a lightweight formatted reply and you accept that the shortcut will normalize and rewrite parts of the content before sending.
- Use `--content` when you need exact `post` JSON, a card, a title, multiple locales, or any structure that `--markdown` cannot express reliably.

## What `--markdown` Really Does

`--markdown` does **not** send arbitrary raw Markdown to the API.

The shortcut:

1. Forces `msg_type=post`
2. Resolves remote Markdown images like `![x](https://...)`
3. Normalizes the Markdown for Feishu post rendering
4. Wraps the final content as:

```json
{"zh_cn":{"content":[[{"tag":"md","text":"..."}]]}}
```

So `--markdown` is a convenience mode, not a full Markdown compatibility layer.

### Current Markdown Caveats

- It does **not** promise full CommonMark / GitHub Flavored Markdown support.
- It always becomes a `post` payload with a single `zh_cn` locale.
- It does **not** let you set a `post` title.
- Headings are rewritten:
    - `# Title` becomes `#### Title`
    - `##` to `######` are normalized to `#####` when the content contains H1-H3
- Consecutive headings are separated with blank lines after heading normalization.
- Block spacing and line breaks may be normalized during conversion.
- Code blocks are preserved as code blocks.
- Excess blank lines are compressed.
- Only remote `http://...`, `https://...`, or already-uploaded `img_xxx` Markdown images are kept reliably.
- Local paths in Markdown image syntax like `![x](./a.png)` are **not** auto-uploaded by `--markdown`.
- If remote Markdown image handling fails, that image is removed with a warning.

If you need exact output, use `--msg-type post --content ...` instead of `--markdown`.

## Preserving Formatting

If the reply contains multiple lines, code blocks, indentation, tabs, or a lot of escaping, prefer `$'...'`.

### When formatting must be preserved

Use `--text` plus `$'...'`:

```bash
lark-cli im +messages-reply --message-id om_xxx --text $'Received\nI will check this today.\nOwner: alice'
```

```bash
lark-cli im +messages-reply --message-id om_xxx --text $'```sql\nselect * from jobs;\n```'
```

This keeps the reply as plain text instead of converting it to a `post`.

### When formatting does not need exact preservation

Use `--markdown`:

```bash
lark-cli im +messages-reply --message-id om_xxx --markdown $'## Follow-up\n\n- I reproduced it\n- I am fixing it'
```

This is better for quick readable formatting, but the final payload may still differ from the source text because headings and spacing are normalized before sending.

## Commands

```bash
# Reply to a message (plain text, --text is recommended for normal replies)
lark-cli im +messages-reply --message-id om_xxx --text "Received"

# Equivalent manual JSON
lark-cli im +messages-reply --message-id om_xxx --content '{"text":"Received"}'

# Reply as a bot
lark-cli im +messages-reply --message-id om_xxx --text "bot reply" --as bot

# Reply with preserved multi-line text
lark-cli im +messages-reply --message-id om_xxx --text $'Line 1\nLine 2\n  indented line'

# Reply inside the thread (message appears in the target thread)
lark-cli im +messages-reply --message-id om_xxx --text "Let's discuss this" --reply-in-thread

# Reply with basic Markdown (will be converted to post JSON)
lark-cli im +messages-reply --message-id om_xxx --markdown $'## Reply\n\n- item 1\n- item 2'

# If you need exact post structure, send JSON directly
lark-cli im +messages-reply --message-id om_xxx --msg-type post --content '{"zh_cn":{"title":"Reply","content":[[{"tag":"text","text":"Detailed content"}]]}}'

# Reply with a local image (uploaded automatically before sending)
lark-cli im +messages-reply --message-id om_xxx --image ./photo.png

# Reply with a local file (uploaded automatically before sending)
lark-cli im +messages-reply --message-id om_xxx --file ./report.pdf

# Reply with a local video (--video-cover is required as the video cover)
lark-cli im +messages-reply --message-id om_xxx --video ./demo.mp4 --video-cover ./cover.png

# With an idempotency key
lark-cli im +messages-reply --message-id om_xxx --text "Received" --idempotency-key my-unique-id

# Preview the request without executing it
lark-cli im +messages-reply --message-id om_xxx --markdown $'## Test\n\nhello' --dry-run
```

## Parameters

| Parameter | Required | Description |
|------|------|------|
| `--message-id <id>` | Yes | ID of the message being replied to (`om_xxx`) |
| `--msg-type <type>` | No | Message type (default `text`). If you use `--text` / `--markdown` / media flags, the effective type is inferred automatically. Explicitly setting a conflicting `--msg-type` fails validation |
| `--content <json>` | One content option | Exact reply content as JSON. The JSON must match the effective `--msg-type` |
| `--text <string>` | One content option | Plain text reply. Best default when you need exact text and formatting preservation |
| `--markdown <string>` | One content option | Convenience Markdown input. Internally converted to `post` JSON with Feishu-specific normalization |
| `--image <path\|key>` | One content option | Local image path or `image_key` (`img_xxx`) |
| `--file <path\|key>` | One content option | Local file path or `file_key` (`file_xxx`) |
| `--video <path\|key>` | One content option | Local video path or `file_key`; **must be used together with `--video-cover`** |
| `--video-cover <path\|key>` | **Required with `--video`** | Video cover image path or `image_key` (`img_xxx`) |
| `--audio <path\|key>` | One content option | Local audio path or `file_key` |
| `--reply-in-thread` | No | Reply inside the thread. The reply appears in the target message's thread instead of the main chat stream |
| `--idempotency-key <key>` | No | Idempotency key; the same key sends only one reply within 1 hour |
| `--as <identity>` | No | Identity type: `bot` or `user` (default `bot`) |
| `--dry-run` | No | Print the request only, do not execute it |

> **Mutual exclusivity rule:** `--text`, `--markdown`, `--content`, and `--image`/`--file`/`--video`/`--audio` cannot be used together. Media flags are also mutually exclusive with each other.
>
> **Video cover rule:** `--video` **must** be accompanied by `--video-cover`. Omitting `--video-cover` when using `--video` will fail validation. `--video-cover` cannot be used without `--video`.

## Common Mistakes

- Choosing `--markdown` when you actually need exact plain text. If exact line breaks and spacing matter, use `--text`, usually with `$'...'`.
- Assuming `--markdown` supports all Markdown features. It does not; it is converted into a Feishu `post` payload and rewritten first.
- Putting local image paths inside Markdown like `![x](./a.png)`. `--markdown` does not auto-upload those paths.
- Using `--content` without making the JSON match the effective `--msg-type`.
- Explicitly setting `--msg-type` to something that conflicts with `--text`, `--markdown`, or media flags.
- Mixing `--text`, `--markdown`, or `--content` with media flags in one command.

## Return Value

```json
{
  "message_id": "om_xxx",
  "chat_id": "oc_xxx",
  "create_time": "1234567890"
}
```

## Usage Scenarios

### Scenario 1: Reply in the main chat stream

```bash
lark-cli im +messages-reply --message-id om_xxx --text "OK, I will handle it"
```

The reply appears in the main chat stream and references the target message.

### Scenario 2: Reply inside a thread

```bash
lark-cli im +messages-reply --message-id om_xxx --text "Let me take a look at this" --reply-in-thread
```

The reply appears in the target message's thread and does not show up in the main chat stream.

## @Mention Format (text / post)

- Recommended format: `<at user_id="ou_xxx">name</at>`
- @all: `<at user_id="all"></at>`
- The shortcut normalizes common variants like `<at id=...>` and `<at open_id=...>` into `user_id`, but `user_id` remains the recommended documented form

## Notes

- `--message-id` must be a valid message ID in `om_xxx` format
- `--content` must be valid JSON
- When using `--content`, you are responsible for making the JSON structure match the effective `msg_type`
- `--reply-in-thread` adds `reply_in_thread=true` to the API request
- `--reply-in-thread` is mainly meaningful in chats that support thread replies
- `--image`/`--file`/`--video`/`--audio`/`--video-cover` support local file paths; the shortcut uploads first and then sends the reply; file/image upload is bot-only, so when using `--as user`, the upload step is automatically performed with bot identity, and only the final send uses user identity
- If the provided media value starts with `img_` or `file_`, it is treated as an existing key and used directly
- `--markdown` always sends `msg_type=post`
- If you explicitly set `--msg-type` and it conflicts with the chosen content flag, validation fails
- When using `--video`, `--video-cover` is required as the video cover
- `--dry-run` uses placeholder image keys for remote Markdown images and placeholder media keys for local uploads
- Failures return error codes and messages
- `--as user` uses a user access token (UAT) and requires the `im:message.send_as_user` and `im:message` scopes; the reply is sent as the authorized end user
- `--as bot` uses a tenant access token (TAT), and requires the `im:message:send_as_bot` scope
