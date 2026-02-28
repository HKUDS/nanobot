# nanobot WhatsApp Bridge

A lightweight Node.js process that connects [WhatsApp Web](https://web.whatsapp.com/) to the nanobot Python backend using the [Baileys](https://github.com/WhiskeySockets/Baileys) library.

## How It Works

```
WhatsApp ←→ Baileys (Node.js) ←→ WebSocket (localhost:3001) ←→ Python nanobot
```

The bridge:
1. Authenticates with WhatsApp Web via QR code (session saved to disk)
2. Listens for inbound messages and forwards them to nanobot over a local WebSocket
3. Receives send commands from nanobot and delivers them to WhatsApp

The WebSocket binds to `127.0.0.1` only — it is never reachable from the network.

## Prerequisites

- Node.js ≥ 18
- npm

You do **not** need to build or run the bridge manually. `nanobot gateway` and `nanobot channels login` handle it automatically.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `BRIDGE_PORT` | WebSocket port (default: `3001`) |
| `AUTH_DIR` | Directory for WhatsApp session files (default: `~/.nanobot/whatsapp-auth`) |
| `BRIDGE_TOKEN_FILE` | Path to a temporary file containing the auth token (preferred, see Security) |
| `BRIDGE_TOKEN` | Auth token as an env var (legacy fallback — visible in `ps` output) |

## Security: Token Passing

When a `bridgeToken` is set in `~/.nanobot/config.json`, nanobot passes the token via a temporary file rather than as an environment variable:

1. Python writes the token to a `0600` temp file and sets `BRIDGE_TOKEN_FILE` to its path.
2. The bridge reads the file and **immediately deletes it**.
3. The in-memory token is used for all subsequent WebSocket auth.

This prevents the token appearing in `/proc/<pid>/environ` or `ps e` output.

Fallback: if `BRIDGE_TOKEN_FILE` is absent, the bridge reads `BRIDGE_TOKEN` from the environment (legacy behaviour, still works).

## WebSocket Protocol

All messages are newline-delimited JSON frames.

### Python → Bridge (commands)

**Auth** (required as the first message when a token is configured):
```json
{"type": "auth", "token": "<bridge_token>"}
```

**Send a message:**
```json
{"type": "send", "to": "1234567890@s.whatsapp.net", "text": "Hello!"}
```

### Bridge → Python (events)

**Inbound message from a WhatsApp user:**
```json
{
  "type": "message",
  "from": "1234567890@s.whatsapp.net",
  "body": "Hello nanobot!",
  "timestamp": 1709000000,
  "isGroup": false
}
```

**QR code for initial login:**
```json
{"type": "qr", "qr": "<ascii QR string>"}
```

**Connection status change:**
```json
{"type": "status", "status": "open"}
```

**Send acknowledgement:**
```json
{"type": "sent", "to": "1234567890@s.whatsapp.net"}
```

**Error:**
```json
{"type": "error", "error": "message string"}
```

### Auth handshake flow

When a token is configured, the first message from the Python client **must** be an `auth` frame. The bridge closes the connection with code `4003` if the token is wrong, or `4001` if no auth arrives within 5 seconds.

## Session Persistence

WhatsApp session credentials are stored in `AUTH_DIR` (default `~/.nanobot/whatsapp-auth`). This directory should be protected:

```bash
chmod 700 ~/.nanobot/whatsapp-auth
```

Deleting this directory forces a fresh QR code scan on next startup.

## Building (Development Only)

The bridge ships with pre-compiled JavaScript. To rebuild from TypeScript source:

```bash
cd bridge
npm install
npm run build   # tsc → dist/
```

To run in watch mode during development:

```bash
npm run dev
```

## Logging

The bridge logs to stdout. When running via `nanobot gateway`, this output is captured by Python and written to nanobot's log file.

Log prefixes:
- `🐈` — startup banner
- `🌉` — WebSocket server bound
- `🔒` — token authentication enabled
- `🔗` — Python client connected/authenticated
- `🔌` — Python client disconnected

## Troubleshooting

**"QR code not appearing"**
Run `nanobot channels login` — this starts the bridge in interactive mode and prints the QR to the terminal.

**"Session expired / kicked"**
WhatsApp occasionally invalidates linked devices. Re-run `nanobot channels login` to re-authenticate.

**"Bridge port already in use"**
Another process is on port 3001. Set `BRIDGE_PORT` to a different port and update `nanobot/config/schema.py` → `WhatsAppConfig.bridge_port` accordingly.

**"Auth timeout / Invalid token"**
The `bridgeToken` in your config doesn't match. Check `~/.nanobot/config.json` → `channels.whatsapp.bridgeToken`.
