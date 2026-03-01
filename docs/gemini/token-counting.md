# Token Counting

> **Status: Partial** — response usage metadata captured, no pre-request counting
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/tokens

## What It Is

Count tokens before and after API calls for cost estimation and context window management.

## Gemini API Capabilities

### Pre-request counting

```python
response = client.models.count_tokens(
    model="gemini-2.5-flash",
    contents="your text here",
)
# Returns: total_tokens
```

### Post-request metadata (`usage_metadata`)

| Field | Description |
|-------|-------------|
| `prompt_token_count` | Input tokens |
| `candidates_token_count` | Output tokens |
| `total_token_count` | Input + output |
| `thoughts_token_count` | Thinking tokens |
| `cached_content_token_count` | Cached tokens |

### Multimodal token costs

| Modality | Cost |
|----------|------|
| Text | ~4 chars per token |
| Images <=384px | 258 tokens |
| Images (tiled) | 258 tokens per 768x768 tile |
| Video | 263 tokens/second |
| Audio | 32 tokens/second |

### Context window info

Available via `models.get()`: `input_token_limit`, `output_token_limit`

## Nanobot Implementation

**Response metadata captured:** `scorpion/providers/gemini_provider.py` (lines 241-248)

```python
usage: dict[str, int] = {}
if response.usage_metadata:
    um = response.usage_metadata
    usage = {
        "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
        "completion_tokens": getattr(um, "candidates_token_count", 0) or 0,
        "total_tokens": getattr(um, "total_token_count", 0) or 0,
    }
```

**What's implemented:**
- Post-request token usage from `usage_metadata`
- Prompt, completion, and total token counts

**What's missing:**
- `count_tokens()` pre-request counting
- `thoughts_token_count` tracking
- `cached_content_token_count` tracking
- Context window limit checking before requests
