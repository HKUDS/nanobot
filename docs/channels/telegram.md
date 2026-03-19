# Telegram

Telegram is the recommended starter channel for nanobot. Setup is simple, the connection is stable, and it works without a public IP or webhook.

---

## Prerequisites

- A Telegram account
- Access to `@BotFather` to create a bot

---

## Step 1: Create the bot

1. Open Telegram and search for **`@BotFather`**
2. Send `/newbot`
3. Follow the prompts and enter a bot name (display name, e.g. `My Nanobot`)
4. Pick a bot username (must end with `bot`, e.g. `my_nanobot_bot`)
5. BotFather returns your **bot token**, for example:

```
123456789:ABCdefGhIJKlmNoPQRstuVWXyz
```

Save the token securely—they are required for configuration.

---

## Step 2: Obtain your user ID

Add your Telegram user ID to `allowFrom` so only authorized users can interact with the bot.

**How to get it:**

1. Open Telegram settings → Profile to see your username (`@yourUsername`)
2. Or message the bot—nanobot logs will print the numeric ID

!!! tip "Username vs. numeric ID"
    You may put either the numeric ID (e.g. `"123456789"`) or the username without the `@` (e.g. `"yourUsername"`) into `allowFrom`.

---

## Step 3: Configure `config.json`

Update `~/.nanobot/config.json` with the following section:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

### Full available settings

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "proxy": null,
      "replyToMessage": false,
      "groupPolicy": "mention"
    }
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Whether the channel is active |
| `token` | `""` | BotFather-issued token |
| `allowFrom` | `[]` | Whitelisted user IDs or usernames |
| `proxy` | `null` | HTTP/SOCKS proxy (e.g. `"http://127.0.0.1:1080"`) |
| `replyToMessage` | `false` | Whether replies quote the original message |
| `groupPolicy` | `"mention"` | How the bot behaves in group chats (see below) |

### `groupPolicy` explained

| Value | Behavior |
|-------|----------|
| `"mention"` (default) | Responds in group chats only when @mentioned |
| `"open"` | Responds to all group messages |

Direct messages always respond regardless of `groupPolicy`.

---

## Step 4: Start the gateway

```bash
nanobot gateway
```

Once it is running, send `/start` or any message to the bot in Telegram to begin interacting.

---

## Available commands

The bot automatically exposes these commands in Telegram’s command menu:

| Command | Description |
|---------|-------------|
| `/start` | Wake the bot up |
| `/new` | Begin a fresh conversation (clears context) |
| `/stop` | Cancel the ongoing task |
| `/help` | Show available commands |
| `/restart` | Restart the bot process |

---

## Voice message transcription

If you configure a Groq API key, Telegram voice notes are transcribed via Whisper automatically:

```json
{
  "providers": {
    "groq": {
      "apiKey": "YOUR_GROQ_API_KEY"
    }
  }
}
```

!!! tip "Free transcription"
    Groq offers free Whisper transcription quota, which is ideal for personal projects.

---

## Using a proxy

If you are in mainland China or another restricted area, configure a proxy:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

Supports `http://`, `https://`, and `socks5://` proxies.

---

## Troubleshooting

**Bot does not respond?**

- Ensure your user ID is listed under `allowFrom`
- An empty `allowFrom` denies everyone by default
- Check the nanobot logs for `Access denied` errors

**Invalid token error?**

- Copy the token again from BotFather—do not include extra spaces
- Revoke and reissue the token via `/revoke` if it is compromised

**Bot silent in group chats?**

- `groupPolicy` set to `"mention"` requires @mentioning the bot
- Confirm the bot is a member of the group and has permission to send messages

**Bot ignores messages from strangers in a group?**

- Add those members to `allowFrom`, or set `allowFrom` to `["*"]` to permit everyone
