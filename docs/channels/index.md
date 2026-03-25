# Channel Overview

**Channels** are the bridges between nanobot and chat platforms. Each channel connects to a specific instant messaging service, funnels user messages into nanobot's message bus, and delivers the AI response back to the platform.

---

## Supported Channels

nanobot currently supports the following 13 platforms:

| Channel | Description | Connection Style |
|---------|-------------|------------------|
| [Telegram](telegram.md) | Recommended starter channel; easy setup and reliable | Long Polling |
| [Discord](discord.md) | Supports community servers, DMs, and file attachments | Gateway WebSocket |
| [Slack](slack.md) | Corporate chat with thread-aware replies | Socket Mode |
| [Feishu / 飞书](feishu.md) | Enterprise messaging with multimodal input | WebSocket Long Connection |
| [DingTalk / 钉钉](dingtalk.md) | Alibaba enterprise messaging platform | Stream Mode |
| [WeCom / 企业微信](wecom.md) | Tencent enterprise messaging | WebSocket Long Connection |
| [Weixin / 微信](weixin.md) | Personal WeChat account via ilinkai API | HTTP Long Polling |
| [QQ](qq.md) | Official QQ bot platform for private and group chats | WebSocket |
| [Email](email.md) | IMAP polling + SMTP replies for asynchronous workflows | IMAP Polling |
| [Matrix](matrix.md) | Decentralized protocol with E2EE support | Matrix Sync |
| [WhatsApp](whatsapp.md) | Connected through the Node.js bridge | WebSocket Bridge |
| [Mochat / Claw IM](mochat.md) | Claw IM open platform integration | Socket.IO |

---

## Enabling Multiple Channels

Set multiple channels to `"enabled": true` under the `channels` object in `~/.nanobot/config.json`. When nanobot starts, the gateway listens on every enabled channel at the same time:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    },
    "discord": {
      "enabled": true,
      "token": "YOUR_DISCORD_BOT_TOKEN",
      "allowFrom": ["YOUR_DISCORD_USER_ID"]
    }
  }
}
```

Start the gateway:

```bash
nanobot gateway
```

All enabled channels run within the same gateway process.

---

## Channel-Specific Settings vs. Global Settings

**Global settings** live at the top level of the `channels` object and apply to every channel:

| Key | Default | Description |
|-----|---------|-------------|
| `sendProgress` | `true` | Stream partial responses to channels while the AI is still composing |
| `sendToolHints` | `false` | Whether to surface tool call hints (e.g., `read_file("…")`) to users |
| `send_max_retries` | `3` | Maximum retry attempts on message send failure (0–10, 0 disables retries) |

**Channel-specific settings** go inside each channel's subsection. Here is an example that combines the global options with a channel override:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

---

## `sendProgress` and `sendToolHints`

### `sendProgress` (default: `true`)

When enabled, nanobot streams partial text back to the channel while it is still composing a response. Users see the bot working instead of waiting for the final answer.

```json
{
  "channels": {
    "sendProgress": true
  }
}
```

### `sendToolHints` (default: `false`)

When turned on, nanobot sends a brief hint message whenever it invokes a tool (for example, web search or shell execution):

```
🔧 web_search("nanobot documentation")
```

This helps users understand what the AI is doing, but it is recommended to disable it in quiet mode.

```json
{
  "channels": {
    "sendToolHints": true
  }
}
```

## Message Retry

When message delivery fails, nanobot automatically retries with exponential backoff (1s, 2s, 4s). This is handled centrally by the channel manager, so all channels benefit from consistent retry behavior.

The number of retry attempts is configurable:

```json
{
  "channels": {
    "send_max_retries": 3
  }
}
```

Valid range: 0-10. Set to 0 to disable retries.

---

## `allowFrom` Access Control

Every channel exposes an `allowFrom` list to control who can interact with the bot:

| Setting | Behavior |
|---------|----------|
| `[]` (empty array) | Deny everyone (default—no one can interact until you configure access) |
| `["USER_ID_1", "USER_ID_2"]` | Allow only the specified users |
| `["*"]` | Allow everyone (public mode—use with caution) |

!!! warning "Security reminder"
    Leaving `allowFrom` empty causes all messages to be rejected. Set your user ID before starting the gateway.

---

## Multi-Instance Deployment

You can keep separate configs for each channel so every instance has its own workspace:

```bash
# Onboard each channel separately
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace

# Start each gateway with its config
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
```

See each channel's dedicated documentation for detailed configuration options.
