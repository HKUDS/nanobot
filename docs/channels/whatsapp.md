# WhatsApp

nanobot connects to WhatsApp through the Node.js bridge, speaking the WhatsApp Web protocol via [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys). The bridge communicates with the nanobot Python process over WebSocket.

---

## Prerequisites

- **Node.js ≥ 18** (required)
- A WhatsApp account with the phone online

---

## Step 1: Verify Node.js version

```bash
node --version
# Should display v18.0.0 or higher
```

Install Node.js from [nodejs.org](https://nodejs.org) if needed.

---

## Step 2: Link your device (scan the QR code)

```bash
nanobot channels login
```

A QR code appears. In WhatsApp:

1. Go to **Settings** → **Linked Devices**
2. Tap **Link a Device**
3. Scan the QR code shown in your terminal

Once linked, the bridge stores its session information, so you do not need to rescan after restarts.

!!! tip "First-time setup"
    `nanobot channels login` automatically downloads and builds the Node.js bridge under `~/.nanobot/bridge/`. The first run may take a moment.

---

## Step 3: Configure `config.json`

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+886912345678"]
    }
  }
}
```

### Full configuration options

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "bridgeToken": "",
      "allowFrom": ["+886912345678"]
    }
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `bridgeUrl` | `"ws://localhost:3001"` | WebSocket URL of the Node.js bridge |
| `bridgeToken` | `""` | Optional bridge auth token (not required by default) |
| `allowFrom` | `[]` | List of allowed WhatsApp numbers (include country code, e.g. `+886912345678`)

---

## Step 4: Run nanobot and the bridge

Open two terminal windows:

```bash
# Terminal 1: start the WhatsApp bridge
nanobot channels login

# Terminal 2: start the gateway
nanobot gateway
```

!!! note "Startup order"
    Start the bridge (`channels login`) before the gateway. The bridge runs in the background to maintain the WhatsApp connection.

---

## Bridge architecture

```
WhatsApp App (phone)
    ↕ WhatsApp Web protocol
Node.js Bridge (~/.nanobot/bridge/)
    ↕ WebSocket (ws://localhost:3001)
nanobot Python (gateway)
    ↕ Message bus
AI Agent
```

The bridge handles WhatsApp’s low-level protocol; nanobot speaks a simple WebSocket message format to it.

---

## Update the bridge

After upgrading nanobot, rebuild the bridge if it changed:

```bash
rm -rf ~/.nanobot/bridge && nanobot channels login
```

!!! warning "Manual rebuild"
    The bridge does not update automatically. After upgrading nanobot, rerun the command to rebuild it.

---

## FAQ

**QR code expires immediately?**

- WhatsApp QR codes time out quickly; scan it right away
- If it fails, rerun `nanobot channels login` to get a new QR code

**Need to rescan after restarting?**

- Normally no; the session info is stored in `~/.nanobot/bridge/`
- To reset, delete that directory and rerun `nanobot channels login`

**Connection drops and does not recover?**

- nanobot retries automatically
- Persistent disconnects may mean WhatsApp revoked the device link; rescan to reconnect

**What is the `allowFrom` format?**

- Use the full international phone number including `+` and country code
- Example for Taiwan: `"+886912345678"`
- Use `[
"*"]` to allow all contacts
