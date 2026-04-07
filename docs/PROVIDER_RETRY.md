# Provider Retry Behavior

Nanobot automatically retries transient LLM provider errors so that temporary
rate limits, overloaded servers, and network hiccups don't kill a conversation.

## Configuration

Set `providerRetryMode` in your `config.json` (or `config.yaml`) under
`agents.defaults`:

```json
{
  "agents": {
    "defaults": {
      "providerRetryMode": "standard"
    }
  }
}
```

| Value | Default | Description |
|-------|---------|-------------|
| `"standard"` | ✅ | Retries up to 3 times with exponential backoff, then returns the error. |
| `"persistent"` | | Retries indefinitely (up to 60 s backoff) until the request succeeds or the same error repeats 10 times. |

## How It Works

### Standard mode

When a provider returns a transient error, nanobot retries with exponential
backoff:

| Attempt | Delay |
|---------|-------|
| 1st retry | 1 s |
| 2nd retry | 2 s |
| 3rd retry | 4 s |

After 3 retries the last error response is returned to the agent loop.

### Persistent mode

Persistent mode keeps retrying past the standard 3-attempt budget:

- Backoff continues at 4 s (capped at 60 s).
- Retries stop after **10 consecutive identical errors** to avoid infinite
  loops on permanent failures.
- Useful for long-running tasks where you'd rather wait for a provider to
  recover than lose the conversation.

### What counts as transient?

Errors containing any of these markers are considered transient and eligible
for retry:

- HTTP status codes: `429`, `500`, `502`, `503`, `504`
- Keywords: `rate limit`, `overloaded`, `timeout`, `timed out`,
  `connection`, `server error`, `temporarily unavailable`

All other errors (e.g. `401 unauthorized`, `400 bad request`) are returned
immediately.

### Retry-After support

Providers can suggest a wait time through:

1. **Structured `retry_after` field** on the response (highest priority).
2. **`Retry-After` HTTP header** — supports both numeric seconds and HTTP-date
   formats.
3. **Text patterns** in the error body, e.g. `"retry after 7s"`,
  `"try again in 20 seconds"`, `"wait 1m before retry"`.

When a retry-after value is provided it is used instead of the default backoff
delay (still capped at 60 s in persistent mode).

### Image fallback

If a non-transient error occurs and the request contained images, nanobot
automatically retries once with images replaced by text placeholders
(e.g. `[image: /path/to/photo.png]`). This handles providers that reject
image content they can't process.

### Progress feedback

During retries, a progress message is streamed to the channel so the user
knows nanobot is waiting:

> Model request failed, retry in 4s (attempt 2).

In persistent mode the message changes to:

> Model request failed, persistent retry in 4s (attempt 5).

## Python SDK

```python
from nanobot import Nanobot

bot = Nanobot.from_config()
result = await bot.run("Hello", session_key="user-1")
```

The retry mode is read from `agents.defaults.providerRetryMode` in your
config file. To override it programmatically, set it before running:

```python
bot.agent_loop.provider_retry_mode = "persistent"
```


