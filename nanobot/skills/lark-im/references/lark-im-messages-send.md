# im +messages-send

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Send a message to a group chat or a direct message conversation. Supports both user identity (`--as user`) and bot identity (`--as bot`).

This skill maps to the shortcut: `lark-cli im +messages-send` (internally calls `POST /open-apis/im/v1/messages`).

## Safety Constraints

Messages sent by this tool are visible to other people. Before calling it, you **must** confirm with the user:

1. The recipient (which person or which group)
2. The message content
3. The sending identity (user or bot)

**Do not** send messages without explicit user approval.

When using `--as bot`, the message is sent in the app's name, so make sure the app has already been added to the target chat.

When using `--as user`, the message is sent as the authorized end user and requires the `im:message.send_as_user` and `im:message` scopes.

## Choose The Right Content Flag

| Need | Recommended flag | Why |
|------|------|------|
| Send plain text exactly as written | `--text` | Wrapped directly to `{"text":"..."}`; no Markdown conversion |
| Send simple Markdown and accept Feishu-style rendering | `--markdown` | Automatically converted to `post` JSON |
| Precisely control the final payload | `--content` | You provide the exact JSON for `text` / `post` / `interactive` / `share_*` / media payloads |
| Send image / file / video / audio | `--image` / `--file` / `--video` / `--audio` | Shortcut uploads local files automatically |

### `--text` vs `--markdown`

- Use `--text` when the content should stay as plain text, including exact line breaks, indentation, code samples, shell snippets, or Markdown characters that should **not** be reinterpreted.
- Use `--markdown` when you want basic Markdown-style rendering and you accept that the shortcut will normalize and rewrite parts of the content before sending.
- Use `--content` when `--markdown` is not enough, especially if you need exact `post` JSON, a title, multiple locales, cards, or unsupported rich structures.

## What `--markdown` Really Does

`--markdown` is **not** sent as raw Markdown API content.

The shortcut does all of the following before sending:

1. Forces `msg_type=post`
2. Resolves remote Markdown images like `![x](https://...)` by downloading and uploading them first
3. Normalizes the Markdown for Feishu post rendering
4. Wraps the result as:

```json
{"zh_cn":{"content":[[{"tag":"md","text":"..."}]]}}
```

This means `--markdown` is convenient, but it is not a full-fidelity Markdown transport.

### Current Markdown Caveats

- It does **not** promise full CommonMark / GitHub Flavored Markdown support.
- It always becomes a `post` payload with a single `zh_cn` locale.
- It does **not** let you set a `post` title. If you need a title, use `--msg-type post --content ...`.
- Headings are rewritten:
    - `# Title` becomes `#### Title`
    - `##` to `######` are normalized to `#####` when the content contains H1-H3
- Consecutive headings are separated with blank lines after heading normalization.
- Block spacing and line breaks may be normalized during conversion.
- Code blocks are preserved as code blocks.
- Excess blank lines are compressed.
- Only `http://...`, `https://...`, or already-uploaded `img_xxx` Markdown images are kept reliably.
- Local paths in Markdown image syntax like `![x](./a.png)` are **not** auto-uploaded by `--markdown`; they may be stripped during optimization.
- If remote Markdown image download/upload fails, that image is removed with a warning.

If any of the above is unacceptable, do **not** use `--markdown`; use `--content` and provide the final JSON yourself.

## Preserving Formatting

If the message has multiple lines, indentation, code blocks, tabs, or many quotes/backslashes, prefer shell ANSI-C quoting with `$'...'`.

This is especially useful in `zsh` / `bash` because it lets you write `\n` explicitly instead of relying on the shell to preserve literal newlines.

### When formatting must be preserved

Use `--text` plus `$'...'`:

```bash
lark-cli im +messages-send --chat-id oc_xxx --text $'Build failed\nBranch: feature/im-docs\nAction: please check logs'
```

```bash
lark-cli im +messages-send --chat-id oc_xxx --text $'```bash\nmake test\nmake lint\n```'
```

Use this path when you want the receiver to see the text exactly as entered, not a converted Markdown post.

### When formatting does not need exact preservation

Use `--markdown`:

```bash
lark-cli im +messages-send --chat-id oc_xxx --markdown $'## Release Notes\n\n- Added send shortcut\n- Added reply shortcut'
```

This is better for lightweight readable formatting, but the final content may not match the source text byte-for-byte because the shortcut normalizes headings and spacing before sending.

## Commands

```bash
# Send plain text (--text is recommended for normal messages)
lark-cli im +messages-send --chat-id oc_xxx --text "Hello"

# Equivalent manual JSON
lark-cli im +messages-send --chat-id oc_xxx --content '{"text":"Hello"}'

# Send to a direct message (pass open_id)
lark-cli im +messages-send --user-id ou_xxx --text "Hello"

# Send multi-line text while preserving formatting
lark-cli im +messages-send --chat-id oc_xxx --text $'Line 1\nLine 2\n  indented line'

# Send basic Markdown (will be converted to post JSON)
lark-cli im +messages-send --chat-id oc_xxx --markdown $'## Update\n\n- item 1\n- item 2'

# If you need exact post structure, send JSON directly
lark-cli im +messages-send --chat-id oc_xxx --msg-type post --content '{"zh_cn":{"title":"Title","content":[[{"tag":"text","text":"Body"}]]}}'

# Send a local image (uploaded automatically before sending)
lark-cli im +messages-send --chat-id oc_xxx --image ./photo.png

# Or send directly with an existing image_key
lark-cli im +messages-send --chat-id oc_xxx --image img_xxx

# Send a local file (uploaded automatically before sending)
lark-cli im +messages-send --chat-id oc_xxx --file ./report.pdf

# Send a video (--video-cover is required as the cover)
lark-cli im +messages-send --chat-id oc_xxx --video ./demo.mp4 --video-cover ./cover.png
lark-cli im +messages-send --chat-id oc_xxx --video ./demo.mp4 --video-cover img_xxx

# Send audio
lark-cli im +messages-send --chat-id oc_xxx --audio ./voice.opus

# Use an idempotency key (same key sends only once within 1 hour)
lark-cli im +messages-send --chat-id oc_xxx --text "Hello" --idempotency-key my-unique-id

# Preview the request without executing it
lark-cli im +messages-send --chat-id oc_xxx --markdown $'## Test\n\nhello' --dry-run
```

## Parameters

| Parameter | Required | Description |
|------|------|------|
| `--chat-id <id>` | One of two | Group chat ID (`oc_xxx`) |
| `--user-id <id>` | One of two | User open_id (`ou_xxx`) for direct messages |
| `--text <string>` | One content option | Plain text message. Best default for exact text and preserved formatting. Automatically wrapped as `{"text":"..."}` |
| `--markdown <string>` | One content option | Convenience Markdown input. Internally converted to `post` JSON with Feishu-specific normalization; not full Markdown passthrough |
| `--content <json>` | One content option | Exact message content JSON string; use this when you need full control over `msg_type` and payload. The JSON must match the effective `--msg-type` |
| `--image <path\|key>` | One content option | Local image path or `image_key` (`img_xxx`). Local paths are uploaded automatically |
| `--file <path\|key>` | One content option | Local file path or `file_key` (`file_xxx`). Local paths are uploaded automatically |
| `--video <path\|key>` | One content option | Local video path or `file_key`. Local paths are uploaded automatically. **Must be paired with `--video-cover`** |
| `--video-cover <path\|key>` | **Required with `--video`** | Video cover image path or `image_key` (`img_xxx`). Local paths are uploaded automatically |
| `--audio <path\|key>` | One content option | Local audio path or `file_key`. Local paths are uploaded automatically |
| `--msg-type <type>` | No | Message type (default `text`). If you use `--text` / `--markdown` / media flags, the effective type is inferred automatically. Explicitly setting a conflicting `--msg-type` fails validation |
| `--idempotency-key <key>` | No | Idempotency key; the same key sends only one message within 1 hour |
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

## `content` Format Reference

| `msg_type` | Example `content` |
|----------|-------------|
| `text` | `{"text":"Hello <at user_id=\"ou_xxx\">name</at>"}` |
| `post` | `{"zh_cn":{"title":"Title","content":[[{"tag":"text","text":"Body"}]]}}` |
| `image` | `{"image_key":"img_xxx"}` |
| `file` | `{"file_key":"file_xxx"}` |
| `audio` | `{"file_key":"file_xxx"}` |
| `media` | `{"file_key":"file_xxx","image_key":"img_xxx"}` (video; `image_key` is the cover from `--video-cover` — **required**) |
| `share_chat` | `{"chat_id":"oc_xxx"}` |
| `share_user` | `{"user_id":"ou_xxx"}` |
| `interactive` | Card JSON (see Feishu interactive card documentation) |

## Return Value

```json
{
  "message_id": "om_xxx",
  "chat_id": "oc_xxx",
  "create_time": "1234567890"
}
```

## @Mention Format (text / post)

- Recommended format: `<at user_id="ou_xxx">name</at>`
- @all: `<at user_id="all"></at>`
- The shortcut normalizes common variants like `<at id=...>` and `<at open_id=...>` into `user_id`, but you should still document examples with `user_id`

## Notes

- `--chat-id` and `--user-id` are mutually exclusive; you must provide exactly one
- `--content` must be valid JSON
- When using `--content`, you are responsible for making the JSON structure match the effective `msg_type`
- `--image`/`--file`/`--video`/`--audio` support local file paths; the shortcut uploads first and then sends the message; file/image upload is bot-only, so when using `--as user`, the upload step is automatically performed with bot identity, and only the final send uses user identity
- If the provided media value starts with `img_` or `file_`, it is treated as an existing key and used directly
- `--markdown` always sends `msg_type=post`, even if you do not explicitly set `--msg-type post`
- If you explicitly set `--msg-type` and it conflicts with the chosen content flag, validation fails
- When using `--video`, `--video-cover` is required as the video cover
- `--dry-run` uses placeholder image keys for remote Markdown images and placeholder media keys for local uploads
- Failures return an error code and message
- `--as user` uses a user access token (UAT) and requires the `im:message.send_as_user` and `im:message` scopes; the message is sent as the authorized end user
- `--as bot` uses a tenant access token (TAT) and requires the `im:message:send_as_bot` scope
- When sending as a bot, the app must already be in the target group or already have a direct-message relationship with the target user
