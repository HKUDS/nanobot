# Nanobot OpenAI-Compatible API: Run a Local Agent Behind /v1/chat/completions

nanobot can expose a minimal OpenAI-compatible endpoint for local integrations. If your agent already replies in the WebUI, open **Settings → System**, configure and start the API service there. You do not need another installation or a separate `nanobot serve` process.

For a terminal-managed API, use your existing configured installation:

```bash
nanobot plugins enable api
nanobot agent -m "Hello!"
nanobot serve
```

Run the CLI check first. If `nanobot agent -m "Hello!"` fails, fix provider or config setup before debugging the API server. By default, the API binds to `127.0.0.1:8900`. You can change this in `config.json`.

For setup help, see [`quick-start.md`](./quick-start.md), [`providers.md`](./providers.md), and [`troubleshooting.md`](./troubleshooting.md).

## Authentication

For graphical setup, open **Settings → System**, find the API service, enter its host, port, and API key, and start it. Set a key before binding to a network interface. The config-file alternative is collapsed below.

Local-only `127.0.0.1` usage does not require an API key. If you bind the API server to all interfaces with `api.host: "0.0.0.0"` or `"::"`, nanobot requires `api.apiKey`; otherwise startup fails to avoid exposing an unauthenticated agent endpoint on the network.

<details>
<summary>Manual configuration</summary>

```json
{
  "api": {
    "host": "0.0.0.0",
    "port": 8900,
    "apiKey": "${NANOBOT_API_KEY}"
  }
}
```

</details>

When `api.apiKey` is set, send it as a Bearer token on API routes. The health endpoint remains unauthenticated so local probes and load balancers can still check process health.

```bash
curl http://127.0.0.1:8900/v1/models \
  -H "Authorization: Bearer $NANOBOT_API_KEY"
```

## Behavior

- Conversation history: pass `"session_id"` in the request body to select a conversation; omit for a shared default session (`api:default`). This is not user authentication or a separate workspace.
- Single-message input: each request must contain exactly one `user` message
- Fixed model: omit `model`, or pass the same model shown by `/v1/models`
- Streaming: set `stream=true` to receive Server-Sent Events (`text/event-stream`) with OpenAI-compatible delta chunks, terminated by `data: [DONE]`; omit or set `stream=false` for a single JSON response
- **File uploads**: supports images, PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx) via JSON base64 or `multipart/form-data` (max 10MB per file)
- API requests run in the synthetic `api` channel. Responses are returned to the HTTP client; the standalone API service does not deliver `message` tool calls to chat apps.

`nanobot serve` creates its own in-process message queue without starting chat-channel consumers. The API service started from **Settings → System** uses the same command. An explicit `channel` and `chat_id` can enqueue a tool message, but it does not cause platform delivery, even when that channel is enabled or a separate gateway is running. Do not treat the tool acknowledgement as a delivery receipt. Applications that need to forward an API result to Telegram, Discord, or another platform must handle that delivery separately.

## Sessions, failures, and retries

All callers use the same configured API key, agent, workspace, long-term memory, and tool permissions. Any authorized caller can select any `session_id`; the server does not bind it to a user identity. A distinct ID separates conversation history, not access to files or memory. Use [separate instances](./multiple-instances.md) for separate trust boundaries, or enforce user-to-session authorization in your own application before forwarding requests.

Requests with the same session ID are serialized within one API process. Different sessions can run concurrently and share workspace files; session locking does not make file changes transactional. Send one turn at a time per conversation when ordering matters.

| Failure | Client-visible result |
|---|---|
| Missing or incorrect configured key | HTTP 401 |
| Invalid request or wrong model | HTTP 400 |
| Oversized or invalid upload | HTTP 413 |
| Non-streaming execution timeout | HTTP 504 |
| Unhandled non-streaming execution failure | HTTP 500 |

These API error responses use `{"error":{"message":"...","type":"...","code":400}}`, with the status code for that failure. An HTTP 200 response can still contain a model or tool failure described in assistant text; it does not certify that the requested action succeeded.

Once an SSE response has started, an execution failure or timeout closes it **without** a final `finish_reason: "stop"` chunk or `data: [DONE]`. There is no separate SSE error event. Treat a stream ending without `[DONE]` as incomplete, even if HTTP status was 200 or some text arrived.

Execution timeout defaults to 120 seconds (`api.timeout`, or `nanobot serve --timeout`). It starts after acquiring the session lock, so waiting behind another request can make total request time longer. A client timeout or disconnect is not a reliable cancellation interface. A failed SSE write cancels its running task, but disconnect detection may wait for output; non-streaming work can continue after a client disconnects. Cancellation and timeout do not undo tool actions already performed.

There is no request idempotency key or automatic deduplication. Retrying can repeat a message, file edit, or external action. Check the result before retrying side-effecting requests, and disable automatic client retries when duplicate actions would matter.

## Endpoints

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

## curl

The examples below use a local server. If you configured `api.apiKey`, set `NANOBOT_API_KEY` to that same value in the client shell; it is separate from your model provider key. The authorization header is ignored when the local server has no configured key.

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Authorization: Bearer $NANOBOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "hi"}],
    "session_id": "my-session"
  }'
```

## File Upload (JSON base64)

Send images inline using the OpenAI multimodal content format:

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Authorization: Bearer $NANOBOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": [
      {"type": "text", "text": "Describe this image"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}}
    ]}]
  }'
```

## File Upload (multipart/form-data)

Upload any supported file type (images, PDF, Word, Excel, PPT) via multipart:

```bash
# Single file
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Authorization: Bearer $NANOBOT_API_KEY" \
  -F "message=Summarize this report" \
  -F "files=@report.docx"

# Multiple files with session isolation
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Authorization: Bearer $NANOBOT_API_KEY" \
  -F "message=Compare these files" \
  -F "files=@chart.png" \
  -F "files=@data.xlsx" \
  -F "session_id=my-session"
```

Supported file types:
- **Images**: PNG, JPEG, GIF, WebP (sent to AI as base64 for vision analysis)
- **Documents**: PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx) (text extracted and sent to AI)
- **Text**: TXT, Markdown, CSV, JSON, etc. (read directly)

## Python (`requests`)

```python
import os

import requests

resp = requests.post(
    "http://127.0.0.1:8900/v1/chat/completions",
    headers={"Authorization": f"Bearer {os.environ.get('NANOBOT_API_KEY', '')}"},
    json={
        "messages": [{"role": "user", "content": "hi"}],
        "session_id": "my-session",  # optional: isolate conversation
    },
    timeout=120,
)
resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
```

## Python (`openai`)

`local-no-key` is only a client-library placeholder for a local server with no key configured. For an authenticated server, supply its actual API key. Discover the configured model instead of copying a provider-specific model ID.

```python
import os

from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8900/v1",
    api_key=os.environ.get("NANOBOT_API_KEY") or "local-no-key",
    max_retries=0,  # A retry could repeat a tool action.
)

model_id = client.models.list().data[0].id
resp = client.chat.completions.create(
    model=model_id,
    messages=[{"role": "user", "content": "hi"}],
    extra_body={"session_id": "my-session"},  # optional: isolate conversation
)
print(resp.choices[0].message.content)
```
