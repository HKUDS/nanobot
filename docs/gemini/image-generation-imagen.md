# Image Generation — Imagen

> **Status: Implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/imagen

## What It Is

Dedicated image generation model (separate from Gemini native). Generates realistic, high-quality images from text prompts. English-only. All outputs include SynthID watermark.

## Gemini API Capabilities

### Models

| Variant | ID | Notes |
|---------|-----|-------|
| Standard | `imagen-4.0-generate-001` | Default |
| Ultra | `imagen-4.0-ultra-generate-001` | Highest quality |
| Fast | `imagen-4.0-fast-generate-001` | Speed-optimized |

### Parameters

- **Number of images:** 1–4 per request (default 4)
- **Size:** 1K or 2K resolution (Standard/Ultra only)
- **Aspect ratios:** 1:1, 3:4, 4:3, 9:16, 16:9 (default 1:1)
- **Person generation:** `dont_allow`, `allow_adult` (default), `allow_all`
- **Max prompt:** 480 tokens
- **Input:** text only (no image editing)

## Nanobot Implementation

**File:** `scorpion/agent/tools/creative.py` (lines 32-130)

```python
# Line 106-115
response = await client.models.generate_images(
    model=model_id,       # imagen-4.0-generate-001
    prompt=prompt,
    config=types.GenerateImagesConfig(
        number_of_images=count,
        aspect_ratio=aspect_ratio,
        person_generation="allow_adult",
    ),
)
```

**What's implemented:**
- All three Imagen 4 variants (standard, ultra, fast)
- `generate_images()` API call
- Number of images (1-4)
- Aspect ratio selection (1:1, 16:9, 9:16, 3:4, 4:3)
- Person generation set to `allow_adult`
- Base64 image extraction and file saving

**What's missing:**
- Resolution control (1K/2K) — not exposed in tool parameters
- Configurable person generation setting
