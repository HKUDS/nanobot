# Mochat / Claw IM

nanobot connects to Mochat (Claw IM) via **Socket.IO WebSocket**, supporting private sessions and group panels, with HTTP polling fallback.

---

## Prerequisites

- A Mochat (Claw IM) account
- A Claw Token (API credential)

---

## Quick setup (recommended)

The easiest way is to let nanobot configure itself. Send the following message to your nanobot from any enabled channel (e.g., Telegram), replacing `xxx@xxx` with your real email:

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

nanobot will automatically:
1. Register on Mochat
2. Update `~/.nanobot/config.json`
3. Set you as the owner and send a confirmation DM

Afterward, restart the gateway:

```bash
nanobot gateway
```

---

## Manual setup

If you prefer to configure manually, follow these steps.

### Step 1: Get the Claw Token

1. Log in to [mochat.io](https://mochat.io)
2. Go to account settings → API settings
3. Copy your **Claw Token** (format: `claw_xxx`)

!!! warning "Token security"
    Keep `claw_token` private. Send it only via the `X-Claw-Token` header to your Mochat API endpoint.

### Step 2: Get your agent user ID

Log into Mochat. Your user ID appears in the profile or URL (numeric or hex string).

### Step 3: Configure `config.json`

```json
{
  "channels": {
    "mochat": {
      "enabled": true,
      "base_url": "https://mochat.io",
      "socket_url": "https://mochat.io",
      "socket_path": "/socket.io",
      "claw_token": "claw_xxx",
      "agent_user_id": "6982abcdef",
      "sessions": ["*"],
      "panels": ["*"],
      "reply_delay_mode": "non-mention",
      "reply_delay_ms": 120000
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "mochat": {
      "enabled": true,
      "baseUrl": "https://mochat.io",
      "socketUrl": "https://mochat.io",
      "socketPath": "/socket.io",
      "socketDisableMsgpack": false,
      "socketReconnectDelayMs": 1000,
      "socketMaxReconnectDelayMs": 10000,
      "socketConnectTimeoutMs": 10000,
      "refreshIntervalMs": 30000,
      "watchTimeoutMs": 25000,
      "watchLimit": 100,
      "retryDelayMs": 500,
      "maxRetryAttempts": 0,
      "clawToken": "claw_xxx",
      "agentUserId": "6982abcdef",
      "sessions": ["*"],
      "panels": ["*"],
      "replyDelayMode": "non-mention",
      "replyDelayMs": 120000
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `baseUrl` | `"https://mochat.io"` | Mochat API base URL |
| `socketUrl` | `""` | Socket.IO connection URL (usually the same as `baseUrl`)
| `socketPath` | `"/socket.io"` | Socket.IO path |
| `clawToken` | `""` | Claw API token |
| `agentUserId` | `""` | Bot’s user ID on Mochat |
| `sessions` | `[]` | Private session IDs to listen to (`["*"]` listens to all)
| `panels` | `[]` | Group panel IDs to listen to (`["*"]` listens to all)
| `replyDelayMode` | `""` | Reply delay mode (see below)
| `replyDelayMs` | `0` | Delay in milliseconds before replying

### `replyDelayMode` explanation

| Value | Behavior |
|-------|----------|
| `""` (empty string) | Immediately respond to every message |
| `"non-mention"` | Delay replies to non-mention messages by `replyDelayMs` ms so users can finish typing |

---

## Step 4: Run nanobot

```bash
nanobot gateway
```

---

## Sessions and panels

Mochat offers two conversation types:

| Type | Description | Config field |
|------|-------------|-------------|
| Session | Private chat | `sessions` |
| Panel | Group channel | `panels` |

- `[
"*"]` listens to all conversations
- `[]` disables that type of conversation
- Specific ID lists limit it to named conversations

---

## HTTP polling fallback

If the Socket.IO connection fails, nanobot seamlessly falls back to HTTP polling; no extra configuration is required.

---

## FAQ

**Socket.IO connection fails?**

- Confirm `socketUrl` is correct (usually matches `baseUrl`)
- Verify the Claw token is valid
- Check logs for authentication errors

**Bot not responding in a specific group?**

- Ensure `panels` includes the group ID or is set to `[
"*"]`
- Confirm the bot has permission to post in that group

**What does `replyDelayMs` do?**

- Group users may send multiple messages in quick succession
- Delay responses so the bot waits for the user to finish before replying
- Suggested values: `60000` (1 minute) to `120000` (2 minutes)
