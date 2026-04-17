# WhatsApp Channel Setup (Docker / Raspberry Pi)

This guide covers setting up the WhatsApp channel when running nanobot in Docker,
including the workarounds required for self-messaging via a linked device.

## Prerequisites

- nanobot running in Docker (see `setup_nanobot_rpi.sh`)
- Node.js ≥ 18 installed in the Docker image (already included)
- A WhatsApp account on your phone

## Step 1 — Link Your Device (Scan QR Code)

Run the login command interactively inside the container (requires a TTY):

```bash
docker exec -it nanobot nanobot channels login whatsapp
```

When the QR code appears, open WhatsApp on your phone:
**Settings → Linked Devices → Link a Device** → scan the QR code.

The session is saved to `~/.nanobot/whatsapp-auth/` on the host and persists
across container restarts.

## Step 2 — Configure

Add the WhatsApp channel to `~/.nanobot/config.json`.

> **Important:** Use your number **without** the `+` prefix (e.g. `61433674165`,
> not `+61433674165`). The bridge strips the `+` from the sender ID internally.

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["61433674165"]
    }
  }
}
```

Then restart the container:

```bash
docker restart nanobot
```

## Step 3 — How to Message Nanobot

Since nanobot is linked as a **Linked Device**, message it by sending a WhatsApp
message **to your own number** (appears as "You" in your contacts). Nanobot will
receive the message and reply.

## Troubleshooting

### "Access denied for sender" in logs

The `allowFrom` number doesn't match the sender ID. Check the logs for the exact
sender ID:

```
Sender phone=61433674165 lid=(empty) → sender_id=61433674165
```

Use that exact value (without `+`) in `allowFrom`.

### WhatsApp bridge not starting

The entrypoint auto-starts the bridge when `~/.nanobot/bridge/dist/index.js`
exists and `~/.nanobot/whatsapp-auth/bridge-token` is present. If the bridge
isn't starting, run the login step again:

```bash
docker exec -it nanobot nanobot channels login whatsapp
```

### Self-messages not received (fromMe issue)

By default, the WhatsApp bridge ignores self-sent messages (`msg.key.fromMe`).
This repo patches that out in `bridge/src/whatsapp.ts` so linked-device
self-messaging works. If you rebuild from upstream HKUDS/nanobot, reapply the
patch or the bot will silently ignore your messages.

See: [HKUDS/nanobot#117](https://github.com/HKUDS/nanobot/issues/117)

### Messages received but no reply

Check that `minimax/minimax-m2.7` (or your configured model) is set in
`~/.nanobot/config.json` under `agents.defaults.model` and that the provider
API key is valid.
