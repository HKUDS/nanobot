# WebSocket Server Channel

Nanobot can act as a WebSocket server, allowing external clients (web apps, CLIs, scripts) to interact with the agent in real time via persistent connections.

## Features

- Bidirectional real-time communication over WebSocket
- Streaming support — receive agent responses token by token
- Token-based authentication (static tokens and short-lived issued tokens)
- Multi-chat multiplexing — one connection can run many concurrent `chat_id`s
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

```text
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

```text
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
  "chat_id": "uuid-v4",
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
  "chat_id": "uuid-v4",
  "text": "Hello",
  "stream_id": "s1"
}
```

**`stream_end`** — signals the end of a streaming segment:

```json
{
  "event": "stream_end",
  "chat_id": "uuid-v4",
  "stream_id": "s1"
}
```

**`runtime_model_updated`** — broadcast when the gateway runtime model changes, for example after `/model <preset>`:

```json
{
  "event": "runtime_model_updated",
  "model_name": "openai/gpt-4.1-mini",
  "model_preset": "fast"
}
```

`model_preset` is omitted when no named preset is active. WebUI clients use this event to keep the displayed model badge in sync across slash commands, config reloads, and settings changes.

**`attached`** — confirmation for `new_chat` / `attach` inbound envelopes (see [Multi-chat multiplexing](#multi-chat-multiplexing)):

```json
{"event": "attached", "chat_id": "uuid-v4"}
```

**`error`** — soft error for malformed inbound envelopes. The connection stays open:

```json
{"event": "error", "detail": "invalid chat_id"}
```

### Client → Server

**Legacy (default chat):** send a plain string, or a JSON object with a recognized text field:

```json
"Hello nanobot!"
```

```json
{"content": "Hello nanobot!"}
```

Recognized fields: `content`, `text`, `message` (checked in that order). Invalid JSON is treated as plain text. These frames route to the connection's default `chat_id` (the one announced in `ready`).

**Typed envelopes (multi-chat):** any JSON object with a string `type` field is a typed envelope:

| `type` | Fields | Effect |
|--------|--------|--------|
| `new_chat` | — | Server mints a new `chat_id`, subscribes this connection, replies with `attached`. |
| `attach` | `chat_id` | Subscribe to an existing `chat_id` (e.g. after a page reload). Replies with `attached`. |
| `message` | `chat_id`, `content` | Send `content` on `chat_id`. First use auto-attaches; no explicit `attach` needed. |

See [Multi-chat multiplexing](#multi-chat-multiplexing) for the full flow.

## Configuration Reference

All fields go under `channels.websocket` in `config.json`.

### Connection

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable the WebSocket server. |
| `host` | string | `"127.0.0.1"` | Bind address. Use `"0.0.0.0"` to accept external connections. |
| `port` | int | `8765` | Listen port. |
| `path` | string | `"/"` | WebSocket upgrade path. Trailing slashes are normalized (root `/` is preserved). |
| `maxMessageBytes` | int | `37748736` | Maximum inbound message size in bytes (1 KB – 40 MB). Default (36 MB) is sized to accept up to 4 base64-encoded image attachments at 8 MB each; lower it if the channel only carries text. |

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

## Multi-chat multiplexing

A single WebSocket can carry many concurrent chats. The server tracks `chat_id -> {connections}` as a fan-out set, so the same chat can also be mirrored across multiple connections (e.g. two browser tabs).

### Typical flow (web UI with a sidebar)

```text
client                                server
  | --- connect -------------------->  |
  | <-- {"event":"ready",              |
  |      "chat_id":"d3..."}   (default)|
  |                                     |
  | --- {"type":"new_chat"} --------->  |
  | <-- {"event":"attached",            |
  |      "chat_id":"a1..."}             |
  |                                     |
  | --- {"type":"message",              |
  |      "chat_id":"a1...",             |
  |      "content":"hi"} ------------>  |
  | <-- {"event":"delta", ...}          |
  | <-- {"event":"stream_end", ...}     |
  |                                     |
  | --- {"type":"attach",               |  # after page reload
  |      "chat_id":"a1..."} --------->  |
  | <-- {"event":"attached", ...}       |
```

### Rules

- Every outbound event carries `chat_id`. Clients must dispatch by that field.
- `chat_id` format: `^[A-Za-z0-9_:-]{1,64}$`. Non-matching values return `error`.
- `message` auto-attaches on first use — no separate `attach` is required for chats the server minted (`new_chat`) on the same connection.
- Errors (invalid envelope, unknown `type`, bad `chat_id`) are soft: the server replies with `{"event":"error","detail":"..."}` and keeps the connection open.

### Backward compatibility

Legacy clients that only send plain text or `{"content": ...}` keep working unchanged: those frames route to the connection's default `chat_id` (the one from `ready`). No config flag is needed.

### Security boundary

`chat_id` is a *capability*: anyone holding a valid WebSocket auth credential and the chat_id can attach to that conversation and see its output. This is safe for nanobot's local, single-user model. Multi-tenant deployments should namespace chat_ids per user (or introduce a per-tenant auth gate) — nanobot does not do this today.

## Security Notes

- **Timing-safe comparison**: Static token validation uses `hmac.compare_digest` to prevent timing attacks.
- **Defense in depth**: `allowFrom` is checked at both the HTTP handshake level and the message level.
- **chat_id as capability**: see [Multi-chat multiplexing](#multi-chat-multiplexing). Auth on the WebSocket handshake is the single line of defense; callers who pass it can attach to any chat_id they know.
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
