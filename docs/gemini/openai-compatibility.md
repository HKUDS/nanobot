# OpenAI Compatibility

> **Status: Not applicable** — scorpion uses native google-genai SDK
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/openai

## What It Is

Drop-in compatibility layer allowing OpenAI SDK libraries to work with Gemini models. Swap `base_url` and API key, keep existing OpenAI code.

## Gemini API Capabilities

### Configuration

```python
from openai import OpenAI
client = OpenAI(
    api_key="GEMINI_API_KEY",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)
```

### Supported features (Beta)

- Chat completions + streaming
- Function calling with tool definitions
- Image understanding (vision)
- Image generation (`gemini-2.5-flash-image`)
- Audio understanding + transcription
- Structured outputs (JSON schemas)
- Text embeddings (`gemini-embedding-001`)
- Batch API
- Model listing
- Reasoning/thinking via `reasoning_effort`
- Context caching via `extra_body`

### Limitations

- Beta status — feature support expanding
- Batch file upload/download not supported via OpenAI SDK
- Some Gemini features need `extra_body` workaround

## Nanobot Implementation

Not applicable. Nanobot uses the native `google-genai` SDK directly (`google.genai.Client`), not the OpenAI compatibility layer. This is the correct approach — native SDK has full feature access.

**Note:** The OpenAI compatibility layer is useful for migrating existing OpenAI codebases. Since scorpion was built Gemini-native, there's no need for this.
