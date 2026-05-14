# Channel Configuration Reference

Detailed configuration for each supported channel.

## Field Types

- **Required**: defaults to empty string `""`, must be filled in before the instance can start
- **Optional**: has a sensible default, can be customized

---

## telegram

**Required:**
- `token` — Bot token from @BotFather

**Notable optional:**
- `proxy` — HTTP proxy URL
- `group_policy` — `"open"` (all messages) or `"mention"` (default, only when @mentioned)
- `streaming` — Enable streaming responses (default: true)
- `reply_to_message` — Reply to the triggering message (default: false)
- `react_emoji` — Emoji for "thinking" reaction (default: `"eyes"`)
- `inline_keyboards` — Enable inline keyboard buttons (default: false)

## discord

**Required:**
- `token` — Bot token from Discord Developer Portal

**Notable optional:**
- `allow_channels` — Restrict to specific channel IDs
- `group_policy` — `"mention"` (default) or `"open"`
- `streaming` — Enable streaming (default: true)
- `proxy` — HTTP proxy URL
- `intents` — Discord gateway intents (default: 37377)
- `read_receipt_emoji` — Emoji for read receipt
- `working_emoji` — Emoji for "working" indicator

## feishu

**Required:**
- `app_id` — Feishu app ID
- `app_secret` — Feishu app secret

**Notable optional:**
- `encrypt_key` — Event encryption key
- `verification_token` — Event verification token
- `domain` — `"feishu"` (default) or `"lark"`
- `group_policy` — `"mention"` (default) or `"open"`
- `streaming` — Enable streaming (default: true)

## dingtalk

**Required:**
- `client_id` — DingTalk app client ID
- `client_secret` — DingTalk app client secret

**Notable optional:**
- `allow_from` — Allowed user IDs

## slack

**Required:**
- `bot_token` — Bot OAuth token (`xoxb-...`)
- `app_token` — App-level token (`xapp-...`)

**Notable optional:**
- `mode` — `"socket"` (default, Socket Mode) or `"webhook"`
- `reply_in_thread` — Reply in thread (default: true)
- `react_emoji` — "thinking" emoji (default: `"eyes"`)
- `done_emoji` — "done" emoji (default: `"white_check_mark"`)
- `group_policy` — `"mention"` (default) or `"open"`
- `dm.enabled` — Enable DM support
- `dm.policy` — DM policy
- `dm.allow_from` — Allowed DM users

## wecom

**Required:**
- `bot_id` — WeCom bot ID
- `secret` — WeCom bot secret

**Notable optional:**
- `allow_from` — Allowed users
- `welcome_message` — Welcome message for new chats

## weixin

**Required:**
- `token` — WeChat Official Account token

**Notable optional:**
- `base_url` — API base URL
- `cdn_base_url` — CDN base URL
- `state_dir` — State persistence directory
- `poll_timeout` — Long polling timeout

## whatsapp

**Required:**
- `bridge_token` — WhatsApp bridge token (auto-generated if absent)

**Notable optional:**
- `bridge_url` — Bridge WebSocket URL (default: `"ws://localhost:3001"`)
- `group_policy` — `"open"` (default) or `"mention"`

## qq

**Required:**
- `app_id` — QQ bot app ID
- `secret` — QQ bot secret

**Notable optional:**
- `msg_format` — `"plain"` or `"markdown"`
- `ack_message` — Acknowledgment message text
- `media_dir` — Media file directory

## email

**Required:**
- `imap_host` — IMAP server hostname
- `imap_username` — IMAP login username
- `imap_password` — IMAP login password
- `smtp_host` — SMTP server hostname
- `smtp_username` — SMTP login username
- `smtp_password` — SMTP login password
- `from_address` — Sender email address

**Notable optional:**
- `imap_port` — IMAP port (default: 993)
- `smtp_port` — SMTP port (default: 587)
- `imap_use_ssl` — Use SSL for IMAP (default: true)
- `smtp_use_tls` — Use TLS for SMTP (default: true)
- `poll_interval_seconds` — Polling interval (default: 30)
- `mark_seen` — Mark emails as read (default: true)
- `max_body_chars` — Max email body length (default: 12000)
- `subject_prefix` — Reply subject prefix (default: `"Re: "`)
- `verify_dkim` — Verify DKIM signatures (default: true)
- `verify_spf` — Verify SPF records (default: true)
- `allowed_attachment_types` — Allowed file extensions
- `max_attachment_size` — Max attachment size in bytes
- `consent_granted` — Must be set to `true` for the channel to start (default: false)
- `auto_reply_enabled` — Enable auto-reply (default: true)

## matrix

**Required:**
- `user_id` — Matrix user ID (e.g. `@bot:matrix.org`)
- `password` or `access_token` — Login password OR access token

**Notable optional:**
- `homeserver` — Homeserver URL (default: `"https://matrix.org"`)
- `device_id` — Device ID
- `e2eeEnabled` — Enable end-to-end encryption (default: true)
- `group_policy` — `"open"`, `"mention"`, or `"allowlist"`
- `streaming` — Enable streaming (default: false)
- `max_media_bytes` — Max media file size (default: 20MB)

## msteams

**Required:**
- `app_id` — Azure AD app ID
- `app_password` — Azure AD app password/secret
- `tenant_id` — Azure AD tenant ID

**Notable optional:**
- `host` — Listen host (default: `"0.0.0.0"`)
- `port` — Listen port (default: 3978)
- `reply_in_thread` — Reply in thread (default: true)
- `validate_inbound_auth` — Validate incoming auth (default: true)

## mochat

**Required:**
- `claw_token` — MoChat Claw token

**Notable optional:**
- `base_url` — API base URL
- `socket_url` — WebSocket URL
- `refresh_interval_ms` — Refresh interval in ms
- `watch_timeout_ms` — Watch timeout in ms

## websocket

Built-in WebSocket channel for programmatic access.

**Required:**
- `token` — Authentication token (enabled by default; set `websocket_requires_token: false` to disable)

**Notable optional:**
- `host` — Listen host (default: `"127.0.0.1"`)
- `port` — Listen port (default: 8765)
- `allow_from` — Allowed origins (default: `["*"]`)
- `streaming` — Enable streaming (default: true)
