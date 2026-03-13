## feat: add exponential backoff retry for LLM API rate limits

Fixes #1558

### Problem

When an LLM provider returns a rate limit error (HTTP 429), nanobot stops immediately without retrying. This is especially painful during high-traffic periods or when using shared API keys, as a single transient 429 kills the entire agent loop.

### Solution

Added a generic, provider-agnostic exponential backoff retry mechanism in `nanobot/providers/retry.py` and integrated it into all three LLM providers.

**Retry behavior:**
- Detects 429 / rate-limit errors from any provider (LiteLLM, OpenAI SDK, httpx, generic HTTP errors)
- Initial delay: 1s, exponential growth: 1s → 2s → 4s → 8s → 16s
- Maximum 5 retry attempts
- Honors `Retry-After` response header when present (takes priority over calculated delay)
- Per-retry delay capped at 60s
- Logs a warning on each retry so users know what's happening
- Raises the original exception if all retries are exhausted (preserves existing error handling)

**Detection strategy:**
- Checks `status_code`, `status`, `http_status` attributes on exceptions (covers litellm, openai, httpx)
- Falls back to string matching for wrapped/custom errors (`"rate limit"`, `"429"`, `"too many requests"`, `"quota exceeded"`)

### Files changed

| File | Change |
|------|--------|
| `nanobot/providers/retry.py` | **New** — generic async `with_retry()` utility with rate-limit detection |
| `nanobot/providers/litellm_provider.py` | Wrap `acompletion()` call with `with_retry()` |
| `nanobot/providers/custom_provider.py` | Wrap OpenAI SDK call with `with_retry()` |
| `nanobot/providers/openai_codex_provider.py` | Wrap `_request_codex()` calls with `with_retry()` |

### Design decisions

- **No new dependencies** — uses only `asyncio` and `loguru` (already in the project)
- **Provider-agnostic** — detection works across all exception types without importing provider-specific classes
- **Minimal invasion** — single `with_retry()` wrapper around existing API calls; no structural changes
- **Composable** — `with_retry()` accepts configurable `max_retries`, `initial_delay`, `backoff_factor`, and `max_delay` for future customization
- **Non-rate-limit errors pass through** — only 429/rate-limit errors trigger retry; all other exceptions propagate immediately

### Example log output

```
WARNING | Rate limit hit (attempt 1/5). Retrying in 1.0s...
WARNING | Rate limit hit (attempt 2/5). Retrying in 2.0s...
WARNING | Rate limit hit (attempt 3/5). Retrying in 4.0s (Retry-After: 3s)...
```
