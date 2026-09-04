# Direct Delivery Webhook

The gateway can accept authenticated HTTP notifications and deliver them directly to an enabled
chat channel **without invoking the agent loop or an LLM**. This is useful for deterministic alerts
from CI, monitoring, billing, or other trusted systems.

Direct delivery is disabled by default and listens on a separate, loopback-only port by default.

## Configuration

Merge this into `~/.nanobot/config.json`:

```json
{
  "gateway": {
    "directDelivery": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 18791,
      "path": "/deliver",
      "secret": "replace-with-a-long-random-secret",
      "channel": "telegram",
      "chatId": "123456789",
      "maxBodyBytes": 65536,
      "maxAgeSeconds": 300,
      "maxRequestsPerMinute": 60
    }
  }
}
```

`channel` must name an enabled channel and `chatId` is that channel's destination identifier.
Keep the listener private when possible. If it must be exposed, place it behind TLS and a reverse
proxy; the shared secret authenticates messages but does not encrypt traffic.

## Request format

Send a JSON object containing the final text to deliver:

```json
{"content":"Production deployment completed"}
```

Required headers:

- `Content-Type: application/json`
- `X-Nanobot-Timestamp`: current Unix timestamp in seconds
- `X-Nanobot-Request-ID`: unique identifier for this delivery attempt
- `X-Nanobot-Signature-256`: `sha256=<hex digest>`

The signature is HMAC-SHA256 over these exact bytes:

```text
<timestamp>.<request-id>.<raw request body>
```

For example, in Python:

```python
import hashlib
import hmac
import json
import time
import uuid

body = json.dumps(
    {"content": "Production deployment completed"},
    separators=(",", ":"),
).encode()
timestamp = str(int(time.time()))
request_id = str(uuid.uuid4())
signature = hmac.new(
    secret.encode(),
    f"{timestamp}.{request_id}.".encode() + body,
    hashlib.sha256,
).hexdigest()
```

The endpoint rejects stale timestamps, invalid signatures, duplicate request IDs, oversized bodies,
and requests above the configured per-minute limit. Replay tracking is kept in memory for the
configured freshness window, so senders should still use globally unique request IDs after a gateway
restart.

A successful request returns HTTP 200 only after the message has been accepted by nanobot's outbound
channel queue. Channel delivery then uses the same retry behavior as other outbound messages.
