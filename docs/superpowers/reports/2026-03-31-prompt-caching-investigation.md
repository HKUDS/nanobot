# 2026-03-31 Prompt Caching Investigation — Comprehensive Report

> Problem: Agent hits 50k tokens/minute rate limit because each turn makes 6-10 LLM
> calls, each resending the full context (~22k static tokens + growing history).
> Scope: Current implementation audit, gap analysis, and actionable recommendations.

---

## 1. Current State: Caching Is Already Implemented

Nanobot already has Anthropic prompt caching. It's in `nanobot/providers/litellm_provider.py:133-183`.

### What `_apply_cache_control()` Does

Called on both `chat()` (line 257) and `stream_chat()` (line 381) before every LLM call.

**Budget allocation (4 blocks max):**
1. **1 block → last tool definition** — caches all 49 tool definitions as a prefix
2. **1 block → first system message** — caches the main system prompt (~12k tokens)
3. **Up to 2 blocks → most recent system messages** — caches guardrail injections, skill content

**How it works:**
```python
# String content → content block array with cache_control
{"role": "system", "content": "..."}
→ {"role": "system", "content": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}

# Last tool gets cache_control
tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
```

### Provider Support

Only enabled for Anthropic (`supports_prompt_caching=True` in `providers_registry.py:176`)
and OpenRouter (`providers_registry.py:104`). The model used is `anthropic/claude-haiku-4-5`.

### Where It's Called

```
User message → MessageProcessor → TurnRunner → StreamingLLMCaller.call()
  → LiteLLMProvider.stream_chat()
    → _apply_cache_control(messages, tools)    ← caching applied here
    → litellm.acompletion(stream=True, ...)    ← sent to Anthropic
```

---

## 2. Gap Analysis: What's Wrong

### Gap 1: Cache Metrics Are Not Tracked (CRITICAL)

`_parse_response()` (line 342) and the streaming path (line 450) only extract:
```python
usage = {
    "prompt_tokens": ...,
    "completion_tokens": ...,
    "total_tokens": ...,
}
```

Anthropic returns additional fields that are **not captured**:
```python
response.usage.cache_creation_input_tokens   # tokens written to cache (1.25x cost)
response.usage.cache_read_input_tokens       # tokens read from cache (0.1x cost)
```

**Impact:** We have no way to verify that caching is actually working. The cache could
be silently broken and we'd never know.

### Gap 2: Guardrail Injections May Break the Cache (HIGH)

The turn runner appends system messages mid-turn at multiple points:

| Location | Line | What | When |
|----------|------|------|------|
| Malformed fallback | 276 | `{"role": "system", "content": _NUDGE_MALFORMED}` | LLM returns unparseable response |
| Final answer nudge | 309 | `{"role": "system", "content": _NUDGE_FINAL}` | Max iterations reached |
| Tool result format | 407 | Tool result as system message | After each tool batch |
| Guardrail intervention | 507 | `{"role": "system", "content": intervention.message}` | Guardrail fires |
| Self-check prompt | 541 | Verification system message | After loop, before final answer |

The `_apply_cache_control()` method caches the **first** system message and the **most
recent** system messages. But the cache is **prefix-based** — Anthropic caches everything
from the start up to the last `cache_control` marker.

When a new system message is appended mid-turn, `_apply_cache_control` re-selects which
messages to cache. The first system message (main prompt) stays cached. But the "most
recent system messages" change every iteration, meaning those 2 cache blocks are
**written fresh each call** instead of being hits.

This is by design — the recent system messages ARE different each turn. The question is
whether those 2 blocks are large enough (≥4,096 tokens for Haiku 4.5) to be worth caching.
Guardrail messages are typically 100-200 tokens — **well below the 4,096 minimum**. Those
cache blocks are wasted.

### Gap 3: Conversation History Is Not Cached (MEDIUM)

The assistant and user messages that accumulate during the tool loop are never cached.
In a 10-call turn, calls 2-10 resend all previous messages. The history from call 1-9
doesn't change when call 10 runs — it could be cached.

However, message content varies per-call (tool results, assistant reasoning), making
prefix-based caching tricky. The "sliding breakpoint" pattern (cache up to the
second-to-last message) is the industry solution but requires careful implementation.

### Gap 4: Tool Definition Order Not Guaranteed (LOW)

`_apply_cache_control` caches tools as a prefix by marking the last tool. For this to
produce cache hits, tool definitions must be **byte-identical** and in the **same order**
across calls. If `ToolRegistry` returns tools in a non-deterministic order (e.g.,
dict iteration order varies), the tool cache breaks silently.

### Gap 5: Rate Limits Count ALL Tokens, Including Cached (CRITICAL)

From the Anthropic docs: **cached tokens still count toward rate limits.** Prompt caching
reduces **cost** (90% cheaper for cache hits) and **latency** (faster processing of
cached prefix), but the rate limit counter counts all input tokens regardless of cache
status.

This means prompt caching alone **does not solve the rate limit problem.** It's a cost
and latency optimization, not a rate limit optimization.

---

## 3. Expected Caching Behavior (Theoretical)

Given the current implementation and a 6-call turn:

| Call | Tools (10k) | System prompt (12k) | Recent system msgs | History |
|------|-------------|--------------------|--------------------|---------|
| 1 | **WRITE** | **WRITE** | (none yet) | (none) |
| 2 | **HIT** | **HIT** | WRITE (skill content) | uncached |
| 3 | **HIT** | **HIT** | MISS (new tool result) | uncached |
| 4 | **HIT** | **HIT** | MISS (new tool result) | uncached |
| 5 | **HIT** | **HIT** | MISS (guardrail, <4096 tokens) | uncached |
| 6 | **HIT** | **HIT** | MISS (new tool result) | uncached |

**Expected savings per turn:**
- Tools: 1 write + 5 hits = 10k × 1.25 + 50k × 0.1 = 17.5k effective tokens (vs 60k without)
- System: 1 write + 5 hits = 12k × 1.25 + 60k × 0.1 = 21k effective tokens (vs 72k without)
- Recent msgs: mostly misses (too small or changing) — no significant savings
- **Total: ~38.5k effective vs ~132k without caching = 71% cost reduction**

But all 132k tokens still count toward the rate limit.

---

## 4. What Other Projects Do

### Claude Code (Gold Standard)

1. **Static system prompt** — no dynamic content injected into the system prompt mid-turn.
   Dynamic data (git status, file contents) goes into messages, not system prompt.
2. **Deferred tool loading** — only core tool names in cached prefix. Full schemas loaded
   on-demand via `ToolSearch`, appended as messages. Keeps tool prefix small and stable.
3. **Sliding breakpoint** — cache advances to include last assistant response each turn.

### Key Insight from "Don't Break the Cache" (arXiv:2601.06007)

Strategic breakpoint placement > naive full-context caching. Cache only what's truly
static. Let dynamic content be uncached suffix.

### Anthropic Auto-Caching (Feb 2026)

Anthropic now automatically caches static prefixes without explicit `cache_control`
markers. But explicit markers still give better control for agentic loops.

---

## 5. Recommendations

### Priority 1: Track Cache Metrics (Diagnostic — must do first)

Before changing anything, we need to know if caching works today.

**Change:** In `_parse_response()` and the streaming usage extraction, capture cache fields:

```python
usage = {
    "prompt_tokens": response.usage.prompt_tokens,
    "completion_tokens": response.usage.completion_tokens,
    "total_tokens": response.usage.total_tokens,
    "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
}
```

Log these to Langfuse. After one test session, we'll know:
- Are cache writes happening? (tools + system prompt on first call)
- Are cache hits happening? (subsequent calls)
- What percentage of tokens are cached?

**Effort:** ~15 lines. **Impact:** Enables all other decisions.

### Priority 2: Stop Wasting Cache Blocks on Small Messages

The 2 "recent system message" cache blocks are mostly wasted on guardrail injections
(100-200 tokens) that don't meet Haiku's 4,096 minimum.

**Change:** Only cache system messages that exceed the model's minimum cacheable threshold:

```python
MIN_CACHEABLE_TOKENS_HAIKU = 4096
CHARS_PER_TOKEN_ESTIMATE = 4

for idx in reversed(system_indices):
    if msg_budget <= 0:
        break
    content = messages[idx].get("content", "")
    estimated_tokens = len(content) // CHARS_PER_TOKEN_ESTIMATE
    if idx not in cache_indices and estimated_tokens >= MIN_CACHEABLE_TOKENS_HAIKU:
        cache_indices.add(idx)
        msg_budget -= 1
```

**Effort:** ~10 lines. **Impact:** Stops wasting cache blocks, saves the write cost.

### Priority 3: Request Rate Limit Increase (Non-Code)

Since cached tokens still count toward rate limits, caching alone won't fix the 50k/min
limit. Contact Anthropic sales to request a higher limit (200k+/min is standard for
agentic use cases).

**Effort:** Email. **Impact:** Directly solves the rate limit problem.

### Priority 4: Add Rate-Aware Delays (Medium Code)

Track cumulative tokens sent in a rolling 60-second window. When approaching the limit,
add a short delay before the next LLM call.

```python
class TokenRateLimiter:
    def __init__(self, max_tokens_per_minute: int):
        self._max = max_tokens_per_minute
        self._window: deque[tuple[float, int]] = deque()

    async def acquire(self, token_count: int) -> None:
        now = time.monotonic()
        # Expire entries older than 60 seconds
        while self._window and now - self._window[0][0] > 60:
            self._window.popleft()
        current = sum(t for _, t in self._window)
        if current + token_count > self._max:
            wait = 60 - (now - self._window[0][0])
            await asyncio.sleep(wait)
        self._window.append((time.monotonic(), token_count))
```

**Effort:** ~50 lines + integration. **Impact:** Prevents rate limit errors entirely.

### Priority 5: Stabilize Tool Definition Order

Verify that `ToolRegistry` returns tools in a deterministic order across calls.

**Effort:** Check + maybe sort. **Impact:** Ensures tool cache hits.

### Priority 6: Consider Reducing System Prompt Size (Long-Term)

The system prompt is ~12k tokens. The 49 tool definitions add ~10k. That's 22k tokens
of static context per call. Strategies:

- **Deferred tool loading** (Claude Code pattern): Only include ~10 core tools in the
  cached prefix. Load specialized tools on-demand.
- **Compress identity/memory sections**: Some sections may be verbose.
- **Dynamic tool filtering**: Only send tools relevant to the loaded skill.

**Effort:** Significant refactoring. **Impact:** Reduces both cost and rate limit pressure.

---

## 6. Summary

| Finding | Severity | Status |
|---------|----------|--------|
| Caching is implemented | ✅ | Working (probably) |
| No cache metrics tracked | CRITICAL | Cannot verify it works |
| Cached tokens still count toward rate limit | CRITICAL | Caching alone won't fix rate limits |
| Cache blocks wasted on small guardrail messages | HIGH | Easy fix |
| Conversation history uncached | MEDIUM | Known tradeoff |
| Tool definition order not guaranteed | LOW | Needs verification |

**The key insight:** Prompt caching is a **cost optimization** (up to 71% cheaper), not
a **rate limit solution**. The rate limit problem requires either a limit increase from
Anthropic or rate-aware delays in the LLM caller. Both should be pursued.

**Recommended order:**
1. Add cache metrics (verify current caching works)
2. Request rate limit increase (solves the immediate problem)
3. Add rate-aware delays (prevents future rate limit errors)
4. Fix wasted cache blocks (cost optimization)
5. Stabilize tool order (cache reliability)
6. Consider deferred tool loading (long-term)
