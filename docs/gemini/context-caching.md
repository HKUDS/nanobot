# Context Caching

> **Status: Partial** — architecture supports cache-friendly prompts, not wired to API
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/caching

## What It Is

Cache large, repeated content (system prompts, documents, videos) to reduce cost and latency on subsequent requests.

## Gemini API Capabilities

### Two mechanisms

**Implicit caching** (automatic)
- Enabled by default on most models
- No developer action needed
- Strategy: put large content at prompt start, send similar requests quickly

**Explicit caching** (manual)
- Guaranteed cost savings
- Developer creates and manages cache objects

### Minimum tokens

| Model | Minimum |
|-------|---------|
| Gemini 3.1 Pro | 4,096 |
| Gemini 3 Flash | 1,024 |
| Gemini 2.5 Flash | 1,024 |
| Gemini 2.5 Pro | 4,096 |

### TTL

- Default: 1 hour
- Configurable via duration string (`"300s"`) or expiration timestamp

### Supported content

- Video files (via Files API)
- PDF documents
- Text files
- System instructions

### Cost structure

1. Cached tokens billed at reduced rate when reused
2. Storage charges based on TTL
3. Non-cached input + output tokens at standard rates
4. ~4x cost reduction for repeated queries

### Operations

- `caches.create()` — create with model, content, TTL
- Reference via `cached_content` parameter in generation requests
- List, update (TTL only), delete operations
- Cannot retrieve cached content itself; only metadata

### Ideal use cases

- Chatbots with long system instructions
- Repeated video/document analysis
- Recurring code repository queries

## Nanobot Implementation

**Architecture:** Tests exist (`tests/test_context_prompt_cache.py`) validating cache-friendly prompt structure:
- System prompt stability (reusable across requests)
- Runtime context as separate user message
- Session history is append-only

**Gap:** The `GenerateContentConfig` in `gemini_provider.py` does not include `cached_content` parameter. No cache creation or management.

**What's needed:**
```python
# Create cache
cache = client.caches.create(
    model="gemini-2.5-flash",
    config=types.CreateCachedContentConfig(
        system_instruction=system_prompt,
        contents=large_context,
        ttl="3600s",
    ),
)
# Use in requests
config = types.GenerateContentConfig(
    cached_content=cache.name,
    ...
)
```
