# im +messages-resources-download

> **Prerequisite:** Read [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) first to understand authentication, global parameters, and safety rules.

Download image or file resources from a message. Resources are identified by the combination of `message_id` + `file_key`, both of which come directly from message content returned by `im +chat-messages-list`.

> **Note:** read-only message commands render resource keys in message content, but they do not download binaries automatically. Use this command whenever you need to fetch the actual image/file bytes or save them to a specific path.

This skill maps to the shortcut: `lark-cli im +messages-resources-download` (internally calls `GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}`).

## Commands

```bash
# Download an image (save to the current directory)
lark-cli im +messages-resources-download --message-id om_xxx --file-key img_v3_xxx --type image

# Download a file
lark-cli im +messages-resources-download --message-id om_xxx --file-key file_v3_xxx --type file

# Specify the output path
lark-cli im +messages-resources-download --message-id om_xxx --file-key img_v3_xxx --type image --output ./photo.png

# Download as a bot
lark-cli im +messages-resources-download --message-id om_xxx --file-key img_v3_xxx --type image --as bot

# Preview the request without executing it
lark-cli im +messages-resources-download --message-id om_xxx --file-key img_v3_xxx --type image --dry-run
```

## Parameters

| Parameter | Required | Description |
|------|------|------|
| `--message-id <id>` | Yes | Message ID (`om_xxx` format) |
| `--file-key <key>` | Yes | Resource key (`img_xxx` or `file_xxx`) |
| `--type <type>` | Yes | Resource type: `image` or `file` |
| `--output <path>` | No | Output path (relative paths only; `..` traversal is not allowed; defaults to `file_key` as the file name) |
| `--as <identity>` | No | Identity type: `user` (default) or `bot` |
| `--dry-run` | No | Print the request only, do not execute it |

## `file_key` Sources

Different resource markers in message content correspond to different `file_key` and `type` values:

| Message Type | Marker in Content | `file_key` Format | `--type` |
|---------|-------------|---------------|--------|
| Image | `img_xxx` | `img_xxx` | `image` |
| File | `file_xxx` | `file_xxx` | `file` |
| Audio | `file_xxx` | `file_xxx` | `file` |
| Video | `file_xxx` | `file_xxx` | `file` |

## Usage Scenario

### Scenario: Extract and download an image from a message

```bash
# Step 1: Fetch messages and find one containing an image
lark-cli im +chat-messages-list --chat-id oc_xxx
# In the response you see: { "msg_type": "image", "content": "{\"image_key\":\"img_v3_xxx\"}" }

# Step 2: Download the image
lark-cli im +messages-resources-download --message-id om_xxx --file-key img_v3_xxx --type image
```

## Common Errors and Troubleshooting

| Symptom | Root Cause | Solution |
|---------|---------|---------|
| Download failed | `file_key` does not match the `message_id` | Make sure the `file_key` came from that message's content |
| Hit error code 234002 or 14005 | No permission, **not** missing API scope | no access to this chat or file was deleted — do not retry, return the error to the user |
| Permission denied | `im:message:readonly` is not authorized | Have the agent run `lark-cli auth login --scope "im:message:readonly"` in the background and return the authorization link; do not ask the end user to run the command manually |
| File too large | Over the 100 MB limit | This is a Feishu API limitation and cannot be bypassed with this endpoint |

## References

- [lark-im](../SKILL.md) - all message-related commands
- [lark-shared](../../lark-shared/SKILL.md) - authentication and global parameters
