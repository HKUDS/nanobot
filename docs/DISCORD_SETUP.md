# Discord Channel Setup Guide

This guide covers everything needed to connect nanobot to Discord — both Direct Messages and server text channels.

## Prerequisites

- A Discord application with a bot user ([Discord Developer Portal](https://discord.com/developers/applications))
- nanobot installed and running (`nanobot gateway`)

---

## Step 1 — Enable Privileged Gateway Intents

In the Discord Developer Portal → your app → **Bot** → **Privileged Gateway Intents**, enable:

- ✅ **Message Content Intent** — without this, Discord delivers events but with empty `content`; nanobot will silently skip all messages

---

## Step 2 — Set Bot Permissions

When inviting the bot to your server, include at minimum:

| Permission | Why |
|------------|-----|
| View Channels | Bot must see the channel to receive events |
| Send Messages | Bot must be able to reply |
| Read Message History | Required for context in conversations |

Generate the invite URL in **OAuth2 → URL Generator**, select `bot` scope, check the permissions above.

> **Note:** Channel-level permission overrides can block these even if the role has them server-wide. Check **Channel Settings → Permissions** if the bot is still silent after granting role permissions.

---

## Step 3 — Configure nanobot

Edit `~/.nanobot/config.json`:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_DISCORD_USER_ID"],
      "groupPolicy": "open"
    }
  }
}
```

### Key fields

| Field | Type | Description |
|-------|------|-------------|
| `token` | string | Bot token from Developer Portal → Bot → Reset Token |
| `allowFrom` | string[] | Discord User IDs allowed to talk to the bot. Use `["*"]` to allow everyone |
| `groupPolicy` | `"mention"` \| `"open"` | Controls server channel behavior (see below) |

### `groupPolicy` explained

| Value | Behavior |
|-------|----------|
| `"mention"` | **(default)** Bot only responds in server channels when @mentioned |
| `"open"` | Bot responds to any message from users in `allowFrom`, no @mention needed |

> **DMs are not affected by `groupPolicy`** — direct messages always bypass this check.

### Finding your Discord User ID

Enable **Developer Mode** in Discord → Settings → Advanced, then right-click your avatar → **Copy User ID**.

---

## Step 4 — Restart the gateway

```bash
# If running via systemd
systemctl --user restart nanobot-gateway

# If running directly
nanobot gateway
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| DM works, server channel silent | `groupPolicy` is `"mention"`, not @mentioning | Set `groupPolicy: "open"` or @mention the bot |
| @mention does nothing in server | Bot missing **View Channels** permission | Grant View Channels in server/channel settings |
| Bot receives events but content is empty | **Message Content Intent** not enabled | Enable in Developer Portal → Bot → Privileged Gateway Intents |
| All messages denied (DM and server) | `allowFrom` is empty or wrong user ID | Add your numeric User ID to `allowFrom` |
