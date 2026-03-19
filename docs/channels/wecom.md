# WeCom / 企业微信

nanobot connects to WeCom via the enterprise WeCom AI Bot WebSocket long connection, so no public IP or webhook is needed. Supports text, images, voice, files, and other rich media.

---

## Prerequisites

- A WeCom administrator account
- An enterprise with WeCom AI Bot capability enabled

> nanobot uses the community Python SDK [wecom-aibot-sdk-python](https://github.com/chengyongru/wecom_aibot_sdk), the Python port of the official [@wecom/aibot-node-sdk](https://www.npmjs.com/package/@wecom/aibot-node-sdk).

---

## Step 1: Install the optional dependency

WeCom channel requires the optional SDK:

```bash
pip install nanobot-ai[wecom]
```

Or with `uv`:

```bash
uv pip install nanobot-ai[wecom]
```

---

## Step 2: Create a WeCom AI Bot

1. Visit the [WeCom admin console](https://work.weixin.qq.com/wework_admin/frame)
2. Go to **App Management** → **Smart Robot** → **Create Robot**
3. Choose **API Mode** and select **Long Connection** (WebSocket)
4. After creation, copy the **Bot ID** and **Secret**

!!! tip "Long connection mode"
    With long connection (WebSocket) nanobot initiates the connection to WeCom servers so no public IP is required.

---

## Step 3: Configure `config.json`

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_user_id"]
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_user_id"],
      "welcomeMessage": ""
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `botId` | `""` | WeCom AI Bot ID |
| `secret` | `""` | WeCom AI Bot secret |
| `allowFrom` | `[]` | List of user IDs allowed to interact |
| `welcomeMessage` | `""` | Optional welcome message for first-time users (leave empty to disable) |

---

## Step 4: Run nanobot

```bash
nanobot gateway
```

---

## Capture your user ID

`allowFrom` requires the WeCom user ID (`userid`).

**How to retrieve it:**

1. Temporarily set `allowFrom` to `["*"]`
2. Start nanobot and message the bot
3. Check the logs for your user ID
4. Update `allowFrom` with the specific ID

---

## Multimedia support

WeCom channel handles:

| Message type | Behavior |
|--------------|----------|
| Text | Sent directly to the AI |
| Image | Downloaded and passed to the vision model |
| Voice | Automatically transcribed when Groq is configured |
| File | Downloaded and passed to the AI |
| Mixed content | Parsed as individual components |

---

## FAQ

**Still seeing the optional SDK missing?**

- Ensure you installed in the correct Python environment
- Run `uv sync` or reinstall with `pip install nanobot-ai[wecom]`

**Bot cannot connect?**

- Verify the bot ID and secret
- Make sure you created an API bot using long connection mode
- Review nanobot logs for errors

**How do I configure the welcome message?**

- Set `welcomeMessage` to any string and the bot will send it on the user’s first interaction
- Leave it empty to disable the welcome message
