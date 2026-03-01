# Text Generation

> **Status: Implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/text-generation

## What It Is

Core text generation via `generateContent` API. Accepts text, images, video, and audio inputs and returns text responses. Supports multi-turn chat, streaming, and system instructions.

## Gemini API Capabilities

- **Models:** `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`
- **System instructions** — guide model behavior/persona
- **Multi-turn chat** — conversation history management
- **Streaming** — incremental response delivery via `generateContentStream`
- **Parameters:** temperature, top_p, top_k, stop_sequences, max_output_tokens
- **Multiple candidates** — generate N response variants
- **Safety settings** — configurable content filtering per harm category

## Nanobot Implementation

**File:** `scorpion/providers/gemini_provider.py`

```python
# Line 38-73: chat() method
async def chat(self, messages, tools, model, max_tokens, temperature, reasoning_effort):
    response = await self._client.aio.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max(1, max_tokens),
        ),
    )
```

**What's wired:**
- System instructions via `system_instruction` parameter
- Temperature control
- Max output tokens
- Async generation via `client.aio.models.generate_content()`
- OpenAI-format message conversion to Gemini `Content` objects
- Token usage tracking from `response.usage_metadata`

**What's missing:**
- Streaming (no `generate_content_stream`)
- top_p, top_k sampling parameters
- Stop sequences
- Multiple candidates (`candidate_count`)
- Safety settings configuration
