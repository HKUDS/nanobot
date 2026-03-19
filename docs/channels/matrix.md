# Matrix / Element

nanobot supports the Matrix decentralized protocol and can run on any Matrix homeserver (including matrix.org). Supports end-to-end encryption (E2EE), media attachments, and flexible group access control.

---

## Prerequisites

- A Matrix account (create one for free at [matrix.org](https://matrix.org) or use your self-hosted homeserver)
- Ability to log in with Element or another Matrix client

---

## Step 1: Install Matrix dependencies

Matrix channel requires extra dependencies:

```bash
pip install nanobot-ai[matrix]
```

Or with `uv`:

```bash
uv pip install nanobot-ai[matrix]
```

---

## Step 2: Create or choose a Matrix account

We recommend dedicating an account for nanobot:

1. Visit [app.element.io](https://app.element.io) → **Create account**
2. Choose a homeserver (`matrix.org` by default or enter your own server URL)
3. Confirm you can log in after creating the account

---

## Step 3: Obtain credentials

You need three credentials:

- **userId** (e.g., `@nanobot:matrix.org`)
- **accessToken** (login token)
- **deviceId** (recommended for restoring E2EE state across restarts)

### How to get the access token

**Option 1: through Element client**

1. Log in to Element
2. Click your avatar → **Settings**
3. Go to **Help & About**
4. Scroll to **Access Token** → **Click to reveal**

**Option 2: via API**

```bash
curl -X POST "https://matrix.org/_matrix/client/v3/login" \
  -H "Content-Type: application/json" \
  -d '{"type":"m.login.password","user":"nanobot","password":"YOUR_PASSWORD"}'
```

The response contains `access_token` and `device_id` for your bot.

---

## Step 4: Configure `config.json`

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "allowFrom": ["@your_user:matrix.org"]
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "e2eeEnabled": true,
      "allowFrom": ["@your_user:matrix.org"],
      "groupPolicy": "open",
      "groupAllowFrom": [],
      "allowRoomMentions": false,
      "maxMediaBytes": 20971520,
      "syncStopGraceSeconds": 2
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `homeserver` | `"https://matrix.org"` | Matrix homeserver URL |
| `userId` | `""` | Bot Matrix user ID (`@name:server`) |
| `accessToken` | `""` | Access token for login |
| `deviceId` | `""` | Device ID (recommended for keeping encrypted state) |
| `e2eeEnabled` | `true` | Enable end-to-end encryption (E2EE) |
| `allowFrom` | `[]` | List of allowed Matrix IDs |
| `groupPolicy` | `"open"` | How group room messages are handled (see below) |
| `groupAllowFrom` | `[]` | Room allowlist used when `groupPolicy` is `"allowlist"` |
| `allowRoomMentions` | `false` | Whether to respond to `@room` mentions |
| `maxMediaBytes` | `20971520` | Max bytes per media (0 disables media) |
| `syncStopGraceSeconds` | `2` | Seconds to wait for sync to finish when stopping |

### `groupPolicy` explanation

| Value | Behavior |
|-------|----------|
| `"open"` (default) | Respond to every message in group rooms |
| `"mention"` | Respond only when mentioned |
| `"allowlist"` | Respond only in rooms listed in `groupAllowFrom` |

---

## Step 5: Run nanobot

```bash
nanobot gateway
```

---

## End-to-end encryption (E2EE)

Matrix channels enable E2EE by default:

- Messages between the bot and users are encrypted
- Encryption keys are stored locally in the `matrix-store` directory

!!! warning "Keep the device ID stable"
    Keep `deviceId` the same and do not delete `matrix-store`. Changing these causes the encrypted session to break and the bot may no longer decrypt new messages.

To disable E2EE:

```json
{
  "channels": {
    "matrix": {
      "e2eeEnabled": false
    }
  }
}
```

---

## Media attachments

Matrix supports handling media:

- **Receiving**: images, audio, video, files (including encrypted media)
- **Sending**: AI-generated files are uploaded to the homeserver
- Use `maxMediaBytes` to limit attachment size

---

## FAQ

**Bot cannot see messages in an encrypted room?**

- Confirm `e2eeEnabled` is `true`
- Keep the same `deviceId` and do not delete `matrix-store`
- First startup may require device verification

**Access token expired?**

- Most Matrix access tokens are long-lived but become invalid after logging out from all devices
- Reauthenticate and capture a new `accessToken` and `deviceId`

**Bot not replying in group rooms?**

- Default `groupPolicy` is `"open"`, so it should respond to everyone
- Ensure the bot is invited to the room
- Check logs for permission errors

**How to configure a self-hosted homeserver?**

- Set `homeserver` to your server URL (e.g., `"https://matrix.example.com"`)
- Other settings remain the same
