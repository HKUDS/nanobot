# Feishu / 飞书

nanobot connects to Feishu via a **WebSocket long connection**, so no public IP or webhook is required. Supports multimodal input (images, files), mention-based control in groups, and reply quoting.

---

## Prerequisites

- A Feishu account
- A corporate or team Feishu workspace with permission to create apps

---

## Step 1: Create a Feishu app

1. Visit the [Feishu Open Platform](https://open.feishu.cn/app)
2. Click **Create Internal App**, enter a name and description
3. In the app settings, open **Capabilities** → **Robot** and enable the robot capability

---

## Step 2: Grant permissions

Go to **Development Settings** → **Permission Management**, search for, and add the following permissions:

- `im:message` — send and receive messages in one-on-one and group chats
- `im:message.p2p_msg:readonly` — receive private chat messages
- (Optional) `im:message.group_at_msg:readonly` — receive messages where the bot is mentioned in groups

---

## Step 3: Subscribe to events and choose long connection mode

1. In **Development Settings** → **Event Subscriptions**
2. Add the event `im.message.receive_v1` (message reception)
3. **Select “Use long connection to receive events”** (Long Connection mode)

!!! tip "No public IP needed"
    Long connection mode lets nanobot initiate the connection to Feishu, so you do not need a webhook URL or public IP.

---

## Step 4: Get App ID and App Secret

1. Open **Credentials & Basic Info**
2. Copy the **App ID** (format: `cli_xxx`)
3. Copy the **App Secret**

---

## Step 5: Publish the app

Go to **Version & Release** → create a version → submit for release (enterprise apps require admin approval).

!!! note "Development testing"
    During development you can skip publishing and test directly through the **Online Testing** feature.

---

## Step 6: Configure `config.json`

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "YOUR_APP_SECRET",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "YOUR_APP_SECRET",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "reactEmoji": "THUMBSUP",
      "groupPolicy": "mention",
      "replyToMessage": false
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `appId` | `""` | Feishu app ID |
| `appSecret` | `""` | Feishu app secret |
| `encryptKey` | `""` | Message encryption key (can stay empty in long connection mode) |
| `verificationToken` | `""` | Event verification token (can stay empty in long connection mode) |
| `allowFrom` | `[]` | List of user open IDs allowed to interact |
| `reactEmoji` | `"THUMBSUP"` | Emoji reaction added when a message is received |
| `groupPolicy` | `"mention"` | How group messages are handled (see below) |
| `replyToMessage` | `false` | Whether replies quote the original message |

### `groupPolicy` explanation

| Value | Behavior |
|-------|----------|
| `"mention"` (default) | Respond only when mentioned in a group |
| `"open"` | Respond to every message in a group |

Private chats always respond regardless of `groupPolicy`.

---

## Step 7: Run nanobot

```bash
nanobot gateway
```

---

## Capture your Open ID

Set `allowFrom` to the Feishu user open ID (format: `ou_xxxxxxxx`).

**How to get it:**

1. Temporarily set `allowFrom` to `["*"]` to allow all users
2. Start nanobot and send a message to the bot
3. Check the nanobot logs to find your open ID
4. Update `allowFrom` to the specific ID

---

## Multimodal support

Feishu supports the following media types:

- **Images**: sent directly to the AI for visual processing
- **Voice**: automatically transcribed if a Groq API key is configured
- **Files**: downloaded and forwarded to the AI
- **Stickers**: displayed as `[sticker]`

---

## FAQ

**Bot cannot receive messages?**

- Ensure the app is published and the bot capability is enabled
- Verify `im.message.receive_v1` is subscribed
- Confirm long connection mode is selected

**Bot not responding in a group?**

- When `groupPolicy` is `"mention"`, mention the bot to trigger a reply
- Ensure the bot is invited to the group

**Do I need to set `encryptKey`?**

- In long connection mode, `encryptKey` and `verificationToken` can be left empty
- They are required only when using HTTP callback mode
