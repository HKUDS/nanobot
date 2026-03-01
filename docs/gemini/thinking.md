# Thinking / Reasoning

> **Status: Partial** — parameter exists in config but is not forwarded to the Gemini API
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/thinking

## What It Is

Configurable reasoning depth that lets models "think" before responding. Improves quality on complex tasks at the cost of latency and tokens.

## Gemini API Capabilities

### Gemini 3 models — `thinkingLevel`

| Level | Models | Purpose |
|-------|--------|---------|
| minimal | Flash only | Matches "no thinking" for most queries |
| low | 3.1 Pro, 3 Pro, 3 Flash | Minimize latency/cost |
| medium | 3.1 Pro, 3 Flash | Balanced |
| high | All (default) | Maximum reasoning depth |

### Gemini 2.5 models — `thinkingBudget`

- Range: 128–32,768 tokens
- `0` = disable (Flash/Flash-Lite only)
- `-1` = dynamic (auto-adjust per query complexity)

### Additional features

- **Streaming thoughts:** `includeThoughts: true` returns rolling thought summaries
- **Pricing:** output cost = output tokens + thinking tokens
- **Token tracking:** `thoughtsTokenCount` field in response

## Nanobot Implementation

**Config:** `scorpion/config/schema.py`
```python
# Line 229
reasoning_effort: str | None = None  # low / medium / high
```

**Provider:** `scorpion/providers/gemini_provider.py`
```python
# Line 45: parameter accepted
async def chat(self, ..., reasoning_effort: str | None = None) -> LLMResponse:
```

**Gap:** The `reasoning_effort` parameter is accepted by `chat()` but **never forwarded** to `GenerateContentConfig`. The config object (line 53-57) does not include `thinking_config`.

**What's needed:**
```python
config = types.GenerateContentConfig(
    system_instruction=system_instruction,
    temperature=temperature,
    max_output_tokens=max(1, max_tokens),
    thinking_config=types.ThinkingConfig(
        thinking_budget=...,  # or thinking_level=...
    ),
)
```
