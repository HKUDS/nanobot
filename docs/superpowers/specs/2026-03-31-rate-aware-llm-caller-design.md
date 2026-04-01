# Rate-Aware LLM Caller Design

## Problem

Anthropic enforces a 50,000 input tokens/minute rate limit. During multi-turn tool-use
loops, each LLM call resends the full conversation context (system prompt + history +
tool results). A typical 6-7 call turn accumulates 100-130k prompt tokens within 30-60
seconds, exceeding the limit by 2-3x. The agent hits a 429 error mid-turn and the
request fails.

The prompt improvements that made the agent more thorough (10 tool calls vs 2-3)
exacerbated this — more thorough exploration means more tokens per minute.

## Solution

A `RateLimiter` class in `providers/rate_limiter.py` that tracks prompt tokens sent in
a rolling 60-second window. When the window total exceeds 80% of the limit (40k of 50k),
it introduces a short async sleep before the next LLM call. This is injected into
`StreamingLLMCaller` via the composition root.

## Scope

- **Anthropic-only.** The rate limiter is constructed only when the model string
  indicates an Anthropic model (`anthropic/` prefix or `claude` in the name).
- **Hardcoded limit.** 50,000 tokens/minute, 80% threshold. No config fields.
- **Prompt tokens only.** Completion tokens are not counted against input rate limits.

## Architecture

### Placement: `nanobot/providers/rate_limiter.py`

Rate limiting is an infrastructure concern alongside timeouts, retries, and budget
tracking — all of which already live in the providers layer. The `providers/` package
has 7 files (well under the 15-file limit).

The rate limiter has zero dependencies on other nanobot packages (only stdlib). It is
imported by `agent/streaming.py` (allowed: agent/ may import from providers/) and
constructed in `agent/agent_factory.py` (composition root).

### Integration point: `StreamingLLMCaller`

The rate limiter is injected as an optional constructor parameter. Before each LLM call,
the caller invokes `await rate_limiter.wait_if_needed()`. After each call, it invokes
`rate_limiter.record(prompt_tokens)`.

This covers all LLM calls made through the caller: the main tool-use loop calls AND
the self-check call (which also goes through the provider).

### Wiring: `agent_factory.py`

The factory detects Anthropic models and constructs a `RateLimiter` instance, passing
it to `StreamingLLMCaller`.

## Data Model

```python
@dataclass(slots=True)
class TokenRecord:
    timestamp: float   # time.monotonic()
    tokens: int

class RateLimiter:
    _limit: int              # tokens per minute (50_000)
    _threshold: float        # fraction before sleeping (0.80)
    _window: deque[TokenRecord]  # rolling 60-second window
```

## Behavior

1. **Before each LLM call:** `wait_if_needed()` prunes entries older than 60s, sums
   remaining tokens. If total >= limit * threshold, calculates sleep time based on
   when the oldest entry will expire, clamps to 1-15 seconds, and awaits.

2. **After each LLM call:** `record(prompt_tokens)` appends a new entry to the window.

3. **Sleep calculation:** `oldest_entry.timestamp + 60.0 - now + 0.5` (wait until the
   oldest entry expires plus a small buffer). Clamped to [1, 15] seconds.

## What Changes

| File | Change | LOC delta |
|------|--------|-----------|
| `nanobot/providers/rate_limiter.py` | **New** | ~60 |
| `nanobot/providers/__init__.py` | Export `RateLimiter` | +2 |
| `nanobot/agent/streaming.py` | Optional `rate_limiter` param, 2 call sites | +10 |
| `nanobot/agent/agent_factory.py` | Construct `RateLimiter` for Anthropic models | +5 |
| `tests/test_rate_limiter.py` | **New** unit tests | ~80 |

## What Does NOT Change

- `LiteLLMProvider` — untouched
- `TurnRunner` — untouched
- `LLMProvider` protocol — untouched
- `AgentConfig` — no new config fields
- `providers/base.py` — no protocol changes

## Design for Deletion

If Anthropic increases the rate limit or the limit becomes irrelevant:
1. Delete `providers/rate_limiter.py`
2. Remove `rate_limiter` param from `StreamingLLMCaller.__init__`
3. Remove 3 lines from `agent_factory.py`
4. Delete `tests/test_rate_limiter.py`
5. Remove export from `providers/__init__.py`

No cascading changes to TurnRunner, guardrails, or any other component.

## Observability

The rate limiter logs at INFO level when it sleeps, including the duration and current
window total. This appears in structured logs via loguru (consistent with existing
patterns in `streaming.py`).
