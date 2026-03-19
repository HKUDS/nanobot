# Slack

nanobot connects to Slack using **Socket Mode**, so you do not need to expose a public URL or webhook. Supports channel thread replies, file uploads, and emoji reactions.

---

## Prerequisites

- A Slack account
- A workspace where you can install apps

---

## Step 1: Create a Slack app

1. Visit [Slack API](https://api.slack.com/apps)
2. Click **Create New App** → choose **From scratch**
3. Enter an app name and pick your workspace
4. Click **Create App**

---

## Step 2: Enable Socket Mode and get an app token

1. In the left menu, choose **Socket Mode**
2. Toggle **Socket Mode** to ON
3. Click **Generate an app-level token**
4. Enter a token name (e.g. `nanobot-socket`)
5. Click **Add Scope** → select `connections:write`
6. Click **Generate**, then copy the **App-Level Token** (format: `xapp-1-...`)

---

## Step 3: Configure OAuth scopes and bot token

1. In the left menu, select **OAuth & Permissions**
2. Under **Bot Token Scopes**, add:
   - `chat:write` — send messages
   - `reactions:write` — add emoji reactions
   - `app_mentions:read` — read mentions
   - `files:write` — (optional) upload files
3. Click **Install to Workspace** at the top → authorize
4. Copy the **Bot User OAuth Token** (format: `xoxb-...`)

---

## Step 4: Subscribe to events

1. In the left menu, open **Event Subscriptions**
2. Toggle **Enable Events** to ON
3. Under **Subscribe to bot events**, add:
   - `message.im` — receive direct messages
   - `message.channels` — receive channel messages
   - `app_mention` — receive mentions
4. Click **Save Changes**

---

## Step 5: Enable the Messages Tab

1. In the left menu, go to **App Home**
2. Under **Show Tabs**, enable the **Messages Tab**
3. Check **Allow users to send Slash commands and messages from the messages tab**

---

## Step 6: Get your Slack user ID

1. Click your profile in Slack
2. Click **...** → **Copy member ID**

The ID looks like `U0123456789`.

---

## Step 7: Configure `config.json`

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-1-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "botToken": "xoxb-...",
      "appToken": "xapp-1-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention",
      "groupAllowFrom": [],
      "replyInThread": true,
      "reactEmoji": "eyes",
      "doneEmoji": "white_check_mark",
      "dm": {
        "enabled": true,
        "policy": "open",
        "allowFrom": []
      }
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `mode` | `"socket"` | Connection mode (only `"socket"` supported now) |
| `botToken` | `""` | Bot User OAuth Token (`xoxb-...`) |
| `appToken` | `""` | App-Level Token (`xapp-...`) |
| `allowFrom` | `[]` | List of user IDs allowed to interact |
| `groupPolicy` | `"mention"` | How channel messages are handled (see below) |
| `groupAllowFrom` | `[]` | Allowed channel IDs when `groupPolicy` is `"allowlist"` |
| `replyInThread` | `true` | Whether the bot replies in the thread |
| `reactEmoji` | `"eyes"` | Reaction emoji added when a message is received |
| `doneEmoji` | `"white_check_mark"` | Reaction emoji added when a reply completes |
| `dm.enabled` | `true` | Whether to accept direct messages |
| `dm.policy` | `"open"` | Direct message policy |

### `groupPolicy` explanation

| Value | Behavior |
|-------|----------|
| `"mention"` (default) | Respond only when mentioned in a channel |
| `"open"` | Respond to every channel message |
| `"allowlist"` | Respond only in the channels listed in `groupAllowFrom` |

---

## Step 8: Run nanobot

```bash
nanobot gateway
```

Message the bot directly or mention it in a channel to start interacting.

---

## Thread support

`replyInThread` defaults to `true`, so replies appear in the original thread to keep channels tidy.

To disable thread replies:

```json
{
  "channels": {
    "slack": {
      "replyInThread": false
    }
  }
}
```

!!! note "DMs do not use threads"
    Direct messages never appear in threads even if `replyInThread` is `true`.

---

## Disable direct messages

If you only want the bot to operate in channels, disable DMs:

```json
{
  "channels": {
    "slack": {
      "dm": {
        "enabled": false
      }
    }
  }
}
```

---

## FAQ

**Bot not receiving DMs?**

- Ensure the Messages Tab is enabled in App Home
- Verify `message.im` is subscribed

**Bot not responding in channels?**

- Confirm `message.channels` and `app_mention` are subscribed
- If `groupPolicy` is `"mention"`, mention the bot

**What is the `xapp` token?**

- This is the App-Level Token, different from the bot token (`xoxb`)
- Generated on the Socket Mode page for establishing the WebSocket connection

**Do I need to reinstall after scope changes?**

- Yes, re-run **Install to Workspace** after modifying bot scopes to reauthorize
