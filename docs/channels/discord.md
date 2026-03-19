# Discord

nanobot connects to Discord via the Gateway WebSocket, so you do not need to expose a public IP or webhook. Supports thread replies, file uploads, and mention-based control inside servers.

---

## Prerequisites

- A Discord account
- A Discord server to test in

---

## Step 1: Create a Discord application and bot

1. Visit the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** in the upper-right corner, name it, and create
3. In the left menu, select **Bot**
4. Click **Add Bot** (or **Reset Token**) → confirm
5. Click **Copy** to copy the **Bot Token**

!!! warning "Token security"
    The bot token is equivalent to a password. Never commit it to version control or share it. If it leaks, regenerate it on this page immediately.

---

## Step 2: Enable the Message Content Intent

Scroll down the bot settings page to **Privileged Gateway Intents**:

- Tick **MESSAGE CONTENT INTENT** ← **Required; without it the bot cannot read message content**
- (Optional) Tick **SERVER MEMBERS INTENT** if you need to filter access using server membership data

Click **Save Changes**.

---

## Step 3: Get your user ID

1. Go to Discord Settings → **Advanced**
2. Enable **Developer Mode**
3. Right-click your avatar → **Copy User ID**

The ID looks like `123456789012345678`.

---

## Step 4: Invite the bot to your server

1. In the Developer Portal left menu, go to **OAuth2** → **URL Generator**
2. Under **Scopes**, select `bot`
3. Under **Bot Permissions**, select:
   - `Send Messages`
   - `Read Message History`
   - (Optional) `Attach Files` if the bot needs to send attachments
4. Copy the generated URL, open it in a browser, choose your server, and authorize

---

## Step 5: Configure `config.json`

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "gatewayUrl": "wss://gateway.discord.gg/?v=10&encoding=json",
      "intents": 37377,
      "groupPolicy": "mention"
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `token` | `""` | Discord bot token |
| `allowFrom` | `[]` | List of numeric user IDs allowed to interact |
| `gatewayUrl` | Discord default | Gateway WebSocket URL (usually no change needed) |
| `intents` | `37377` | Gateway intents bitmask (usually no change needed) |
| `groupPolicy` | `"mention"` | How to handle messages in group channels (see below) |

### `groupPolicy` explanations

| Value | Behavior |
|-------|----------|
| `"mention"` (default) | Respond only when mentioned in a channel |
| `"open"` | Respond to every message in a channel |

DMs always respond regardless of `groupPolicy`.

---

## Step 6: Run the gateway

```bash
nanobot gateway
```

---

## Thread support

When replying in Discord, nanobot continues within the same thread. Each user conversation keeps its own context.

---

## File attachments

nanobot can receive and send Discord attachments:

- **Receiving**: images, files, etc. are downloaded and passed to the AI for processing
- **Sending**: AI-generated files (code, images) are uploaded as attachments
- Single attachment limit: **20 MB** (Discord free tier limit)

---

## FAQ

**Bot cannot see messages in the server?**

- Ensure **MESSAGE CONTENT INTENT** is enabled; this is the most common issue
- Without the intent, the bot receives events but cannot read message content

**Bot invited but not responding?**

- Ensure your user ID is listed under `allowFrom`
- If `groupPolicy` is `"mention"`, mention the bot in the message

**Bot token invalid?**

- Verify you are using the bot token (not the OAuth client secret)
- Bot tokens often start with `MT` or `NT` and are ~70 characters long

**Rate limit warnings?**

- Discord enforces API rate limits; nanobot automatically retries
- If warnings persist, reduce concurrency of requests
