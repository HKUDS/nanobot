# WebSocket Server Channel

Nanobot can act as a WebSocket server, allowing external clients (web apps, CLIs, scripts) to interact with the agent in real time via persistent connections.

## Features

- Bidirectional real-time communication over WebSocket
- Streaming support — receive agent responses token by token
- Token-based authentication (static tokens and short-lived issued tokens)
- Per-connection sessions — each connection gets a unique `chat_id`
- TLS/SSL support (WSS) with enforced TLSv1.2 minimum
- Client allow-list via `allowFrom`
- Auto-cleanup of dead connections

## Quick Start

### 1. Configure

Add to `config.json` under `channels.websocket`:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8765,
      "path": "/",
      "websocketRequiresToken": false,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

### 2. Start nanobot

```bash
nanobot gateway
```

You should see:

```
WebSocket server listening on ws://127.0.0.1:8765/
```

### 3. Connect a client

```bash
# Using websocat
websocat ws://127.0.0.1:8765/?client_id=alice

# Using Python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8765/?client_id=alice") as ws:
        ready = json.loads(await ws.recv())
        print(ready)  # {"event": "ready", "chat_id": "...", "client_id": "alice"}
        await ws.send(json.dumps({"content": "Hello nanobot!"}))
        reply = json.loads(await ws.recv())
        print(reply["text"])

asyncio.run(main())
```

## Connection URL

```
ws://{host}:{port}{path}?client_id={id}&token={token}
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | No | Identifier for `allowFrom` authorization. Auto-generated as `anon-xxxxxxxxxxxx` if omitted. Truncated to 128 chars. |
| `token` | Conditional | Authentication token. Required when `websocketRequiresToken` is `true` or `token` (static secret) is configured. |

## Wire Protocol

All frames are JSON text. Each message has an `event` field.

### Server → Client

**`ready`** — sent immediately after connection is established:

```json
{
  "event": "ready",
  "chat_id": "uuid-v4",
  "client_id": "alice"
}
```

**`message`** — full agent response:

```json
{
  "event": "message",
  "text": "Hello! How can I help?",
  "media": ["/tmp/image.png"],
  "reply_to": "msg-id"
}
```

`media` and `reply_to` are only present when applicable.

**`delta`** — streaming text chunk (only when `streaming: true`):

```json
{
  "event": "delta",
  "text": "Hello",
  "stream_id": "s1"
}
```

**`stream_end`** — signals the end of a streaming segment:

```json
{
  "event": "stream_end",
  "stream_id": "s1"
}
```

### Client → Server

Send plain text:

```json
"Hello nanobot!"
```

Or send a JSON object with a recognized text field:

```json
{"content": "Hello nanobot!"}
```

Recognized fields: `content`, `text`, `message` (checked in that order). Invalid JSON is treated as plain text.

## Configuration Reference

All fields go under `channels.websocket` in `config.json`.

### Connection

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable the WebSocket server. |
| `host` | string | `"127.0.0.1"` | Bind address. Use `"0.0.0.0"` to accept external connections. |
| `port` | int | `8765` | Listen port. |
| `path` | string | `"/"` | WebSocket upgrade path. Trailing slashes are normalized (root `/` is preserved). |
| `maxMessageBytes` | int | `1048576` | Maximum inbound message size in bytes (1 KB – 16 MB). |

### Authentication

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `token` | string | `""` | Static shared secret. When set, clients must provide `?token=<value>` matching this secret (timing-safe comparison). Issued tokens are also accepted as a fallback. |
| `websocketRequiresToken` | bool | `true` | When `true` and no static `token` is configured, clients must still present a valid issued token. Set to `false` to allow unauthenticated connections (only safe for local/trusted networks). |
| `tokenIssuePath` | string | `""` | HTTP path for issuing short-lived tokens. Must differ from `path`. See [Token Issuance](#token-issuance). |
| `tokenIssueSecret` | string | `""` | Secret required to obtain tokens via the issue endpoint. If empty, any client can obtain tokens (logged as a warning). |
| `tokenTtlS` | int | `300` | Time-to-live for issued tokens in seconds (30 – 86,400). |

### Access Control

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowFrom` | list of string | `["*"]` | Allowed `client_id` values. `"*"` allows all; `[]` denies all. |

### Streaming

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `streaming` | bool | `true` | Enable streaming mode. The agent sends `delta` + `stream_end` frames instead of a single `message`. |

### Keep-alive

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pingIntervalS` | float | `20.0` | WebSocket ping interval in seconds (5 – 300). |
| `pingTimeoutS` | float | `20.0` | Time to wait for a pong before closing the connection (5 – 300). |

### TLS/SSL

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sslCertfile` | string | `""` | Path to the TLS certificate file (PEM). Both `sslCertfile` and `sslKeyfile` must be set to enable WSS. |
| `sslKeyfile` | string | `""` | Path to the TLS private key file (PEM). Minimum TLS version is enforced as TLSv1.2. |

## Token Issuance

For production deployments where `websocketRequiresToken: true`, use short-lived tokens instead of embedding static secrets in clients.

### How it works

1. Client sends `GET {tokenIssuePath}` with `Authorization: Bearer {tokenIssueSecret}` (or `X-Nanobot-Auth` header).
2. Server responds with a one-time-use token:

```json
{"token": "nbwt_aBcDeFg...", "expires_in": 300}
```

3. Client opens WebSocket with `?token=nbwt_aBcDeFg...&client_id=...`.
4. The token is consumed (single use) and cannot be reused.

### Example setup

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "port": 8765,
      "path": "/ws",
      "tokenIssuePath": "/auth/token",
      "tokenIssueSecret": "your-secret-here",
      "tokenTtlS": 300,
      "websocketRequiresToken": true,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

Client flow:

```bash
# 1. Obtain a token
curl -H "Authorization: Bearer your-secret-here" http://127.0.0.1:8765/auth/token

# 2. Connect using the token
websocat "ws://127.0.0.1:8765/ws?client_id=alice&token=nbwt_aBcDeFg..."
```

### Limits

- Issued tokens are single-use — each token can only complete one handshake.
- Outstanding tokens are capped at 10,000. Requests beyond this return HTTP 429.
- Expired tokens are purged lazily on each issue or validation request.

## Security Notes

- **Timing-safe comparison**: Static token validation uses `hmac.compare_digest` to prevent timing attacks.
- **Defense in depth**: `allowFrom` is checked at both the HTTP handshake level and the message level.
- **Token isolation**: Each WebSocket connection gets a unique `chat_id`. Clients cannot access other sessions.
- **TLS enforcement**: When SSL is enabled, TLSv1.2 is the minimum allowed version.
- **Default-secure**: `websocketRequiresToken` defaults to `true`. Explicitly set it to `false` only on trusted networks.

## Media Files

Outbound `message` events may include a `media` field containing local filesystem paths. Remote clients cannot access these files directly — they need either:

- A shared filesystem mount, or
- An HTTP file server serving the nanobot media directory

## Common Patterns

### Trusted local network (no auth)

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 8765,
      "websocketRequiresToken": false,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

### Static token (simple auth)

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "token": "my-shared-secret",
      "allowFrom": ["alice", "bob"]
    }
  }
}
```

Clients connect with `?token=my-shared-secret&client_id=alice`.

### Public endpoint with issued tokens

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 8765,
      "path": "/ws",
      "tokenIssuePath": "/auth/token",
      "tokenIssueSecret": "production-secret",
      "websocketRequiresToken": true,
      "sslCertfile": "/etc/ssl/certs/server.pem",
      "sslKeyfile": "/etc/ssl/private/server-key.pem",
      "allowFrom": ["*"]
    }
  }
}
```

### Custom path

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "path": "/chat/ws",
      "allowFrom": ["*"]
    }
  }
}
```

Clients connect to `ws://127.0.0.1:8765/chat/ws?client_id=...`. Trailing slashes are normalized, so `/chat/ws/` works the same.
