# DingTalk / 钉钉

nanobot connects to DingTalk via **Stream Mode**, so no public IP or webhook is required. Supports private chats, group chats, images, and file attachments.

---

## Prerequisites

- A DingTalk account
- An enterprise account with permission to create apps

---

## Step 1: Create a DingTalk app

1. Visit the [DingTalk Open Platform](https://open-dev.dingtalk.com/)
2. Sign in and go to **App Development** → **Enterprise Internal App**
3. Click **Create App** → choose **DingTalk App**
4. Enter the app name and description, then create

---

## Step 2: Add the robot capability

1. In the app settings, go to **Add App Capabilities** → **Robot**
2. Click **Confirm Add**
3. In the robot configuration:
   - Ensure **Stream Mode** is selected (WebSocket reception, no webhook URL needed)
   - Enter the robot name and description

---

## Step 3: Configure permissions

In **Permission Management**, request permissions as needed:

- `qyapi_chat_group` — group message access (required for group chats)
- Permissions for sending interactive cards (required for rich media replies)

---

## Step 4: Get the Client ID and Client Secret

1. Go to the **Application Credentials** page
2. Copy the **AppKey** (Client ID)
3. Copy the **AppSecret** (Client Secret)

---

## Step 5: Publish the app

Navigate to **Version Management** → create a version → submit for review or publish (internal apps typically publish immediately).

---

## Step 6: Configure `config.json`

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `clientId` | `""` | DingTalk app AppKey (Client ID) |
| `clientSecret` | `""` | DingTalk app AppSecret (Client Secret) |
| `allowFrom` | `[]` | List of staff IDs that can interact |

---

## Step 7: Run nanobot

```bash
nanobot gateway
```

---

## Capture your staff ID

`allowFrom` expects the DingTalk staff ID (format: `user_abc123`).

**How to retrieve it:**

1. Temporarily set `allowFrom` to `["*"]` to allow all users
2. Start nanobot and message the bot
3. Check the nanobot logs for your staff ID
4. Update `allowFrom` accordingly

---

## Multimedia support

DingTalk channel supports:

- **Images**: downloaded and passed to the AI
- **Files**: downloaded before processing
- **RichText**: parses text and embedded media

---

## FAQ

**What is Stream Mode?**

- Stream Mode uses WebSocket connections initiated by nanobot to DingTalk servers
- Requires no public IP or reverse proxy, unlike HTTP callback mode

**Bot not receiving messages?**

- Ensure Stream Mode is selected, not HTTP callback mode
- Confirm the app is published

**Bot ignored in group chats?**

- The bot must be @mentioned in DingTalk groups to respond
- Make sure the robot is invited to the group
