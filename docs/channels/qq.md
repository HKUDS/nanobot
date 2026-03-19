# QQ

nanobot connects to QQ through the official botpy SDK using WebSocket, so no public IP is required. Supports C2C (private) chats, group mentions, and plain-text or Markdown replies.

---

## Prerequisites

- A QQ account
- Developer access approved on the QQ Open Platform

---

## Step 1: Apply for developer access and create a bot

1. Visit the [QQ Open Platform](https://q.qq.com)
2. Click **Apply Now** → register as an individual or enterprise developer
3. Once approved, go to **Bot Management** → **Create Bot**
4. Fill in the bot details and create the bot

---

## Step 2: Get AppID and AppSecret

1. Open the bot management page
2. Navigate to **Development Settings**
3. Copy the **AppID** and **AppSecret**

---

## Step 3: Configure sandbox testing

Before publishing, test in the sandbox environment:

1. In the bot dashboard, open **Sandbox Configuration**
2. Under **Configure in Message List**, click **Add Member** and enter your QQ number
3. After adding, scan the bot’s QR code with the mobile QQ app
4. Open the bot profile → tap **Send Message** to test

!!! warning "Sandbox vs. production"
    Sandbox is for testing only. For production, submit the bot for review and publish it via the [QQ Bot Docs](https://bot.q.qq.com/wiki/).

---

## Step 4: Configure `config.json`

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_OPENID"],
      "msgFormat": "plain"
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_OPENID"],
      "msgFormat": "plain"
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `appId` | `""` | QQ bot AppID |
| `secret` | `""` | QQ bot AppSecret |
| `allowFrom` | `[]` | List of allowed user open IDs |
| `msgFormat` | `"plain"` | Message format: `plain` or `markdown` |

### `msgFormat` explanation

| Value | Use case |
|-------|----------|
| `"plain"` (default) | Plain text compatible with all QQ clients |
| `"markdown"` | Markdown formatting supported by newer clients |

---

## Step 5: Run nanobot

```bash
nanobot gateway
```

---

## Capture your OpenID

`allowFrom` must list the QQ user’s OpenID, not the QQ number.

**How to retrieve it:**

1. Temporarily set `allowFrom` to `["*"]` to allow everyone
2. Start nanobot and message the bot
3. Check the logs for your OpenID
4. Update `allowFrom` with the specific ID

---

## Group support

Current QQ bot capabilities:

- **C2C (private chat)** — one-on-one messages
- **Group mentions** — mention the bot in a group
- **Direct messages** via guild

---

## Publishing flow

After sandbox testing:

1. In the bot dashboard, go to **Version Management** → create a new version
2. Provide feature descriptions and screenshots
3. Submit for review
4. Publish after approval

See the [QQ Bot docs](https://bot.q.qq.com/wiki/) for complete instructions.

---

## FAQ

**Bot receives messages but does not respond?**

- Ensure your OpenID is listed in `allowFrom`
- Check logs for any “Access denied” errors

**Bot ignores group mentions?**

- The bot must be mentioned in group chats to respond
- Confirm it has been added to the group

**Cannot find the bot in sandbox?**

- Verify your QQ number is added under sandbox configuration
- Use the mobile QQ app (not desktop) to scan the QR code
