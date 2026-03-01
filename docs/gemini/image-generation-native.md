# Image Generation — Nano Banana (Gemini Native)

> **Status: Implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/image-generation

## What It Is

Gemini models with native image generation and editing capabilities. Conversational image creation with multi-turn editing, reference images, and grounding.

## Gemini API Capabilities

### Models

| Model | ID | Purpose |
|-------|-----|---------|
| Nano Banana 2 | `gemini-3.1-flash-image-preview` | High-efficiency, speed-optimized |
| Nano Banana Pro | `gemini-3-pro-image-preview` | Professional assets, advanced reasoning |
| Nano Banana | `gemini-2.5-flash-image` | Speed and efficiency |

### Features

- **Text-to-image** and **image editing** via conversation
- **Multi-turn editing** — iteratively modify images in a chat session
- **Reference images** — up to 14 (10 objects or 6 objects + 5 characters for consistency)
- **Aspect ratios:** 1:1, 1:4, 1:8, 2:3, 3:2, 3:4, 4:1, 4:3, 4:5, 5:4, 8:1, 9:16, 16:9, 21:9
- **Resolutions:** 512px (0.5K), 1K, 2K, 4K
- **Thinking levels:** minimal (default) or high
- **Google Search grounding** — images based on real-time data
- **Image Search grounding** (3.1 Flash) — uses Google Image Search as visual context
- **SynthID watermark** on all generated images
- **Style control:** photorealistic, stylized, text rendering, style transfer

## Nanobot Implementation

**File:** `scorpion/agent/tools/creative.py` (lines 96-151)

```python
# Line 133: Gemini native image generation
response = await client.aio.models.generate_content(
    model="gemini-3.1-flash-image-preview",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
    ),
)
```

**What's implemented:**
- Text-to-image via `generate_content` with `response_modalities=["TEXT", "IMAGE"]`
- `gemini-3.1-flash-image-preview` model
- Base64 image extraction from response
- File saving to workspace

**What's missing:**
- Multi-turn editing (no chat session for images)
- Reference images
- Resolution control (0.5K/1K/2K/4K)
- Aspect ratio selection (for native gen)
- Thinking level control
- Google Search grounding for images
