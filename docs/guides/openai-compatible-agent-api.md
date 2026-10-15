# How to Run an OpenAI-Compatible Agent API with nanobot

nanobot can expose a local OpenAI-compatible endpoint behind `/v1/chat/completions`. This lets existing OpenAI-style clients talk to a tool-using nanobot agent instead of a raw model.

## What you will build

- a working nanobot agent
- a local API server on `127.0.0.1:8900`
- a `/v1/chat/completions` request
- optional session isolation with `session_id`

## When to use this

Use this when an existing client, another language, or a separate process already knows how to call an OpenAI-compatible API. Use the Python SDK when you want in-process access to sessions, memory, runtime helpers, and hooks.

## Start from your current setup

If you already get replies in the WebUI, open **Settings → System**, configure the API service, and start it. Keep that gateway running; do not also start `nanobot serve` on the same port.

If nanobot is not configured yet, complete the [quick start](../quick-start.md) first. For a terminal-managed API using that existing config:

```bash
nanobot plugins enable api
nanobot agent -m "Hello!"
nanobot serve
```

## Make a request

In another terminal, call the chat endpoint. If you configured an API key, set `NANOBOT_API_KEY` to it first:

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Authorization: Bearer $NANOBOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "hi"}],
    "session_id": "demo"
  }'
```

## Production notes

- Pass `session_id` to separate conversation histories. Callers still share files, memory, and tool permissions; it is not a user authorization boundary.
- Streaming uses Server-Sent Events when `stream` is `true`. A stream without `[DONE]` is incomplete; retries can repeat tool actions. See [sessions, failures, and retries](../openai-api.md#sessions-failures-and-retries).
- The API service returns results to its HTTP client; it does not deliver `message` tool calls to chat apps. Forward results from your application when that is needed.
- `/v1/models` reports the fixed model surface expected by compatible clients.
- File uploads are supported through JSON base64 or multipart form data.

## Security notes

- Local `127.0.0.1` usage does not require an API key.
- If `api.host` is `0.0.0.0` or `::`, configure `api.apiKey` before startup.
- Treat the API as agent access, not just model access: tools and workspace permissions still matter.

## Troubleshooting

- If `/v1/chat/completions` fails, test `nanobot agent -m "Hello!"` first.
- If remote clients cannot connect, check `api.host`, `api.port`, firewall, and API key configuration.
- If sessions mix together, pass unique `session_id` values.

## Related nanobot docs

- [Nanobot OpenAI-Compatible API](../openai-api.md)
- [Python SDK](../python-sdk.md)
- [Configuration](../configuration.md)
- [Deployment](../deployment.md)
