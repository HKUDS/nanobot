# Safety Settings

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/safety-settings

## What It Is

Configurable content filtering per harm category. Control how aggressively the model filters potentially harmful content.

## Gemini API Capabilities

### Harm categories

- Harassment
- Hate speech
- Sexually explicit
- Dangerous content

### Block thresholds

| Threshold | Behavior |
|-----------|----------|
| BLOCK_NONE | No filtering |
| BLOCK_ONLY_HIGH | Block only high-probability harm |
| BLOCK_MEDIUM_AND_ABOVE | Block medium+ probability |
| BLOCK_LOW_AND_ABOVE | Most restrictive |

### Configuration

```python
config = types.GenerateContentConfig(
    safety_settings=[
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_ONLY_HIGH",
        ),
    ],
)
```

### Additional safety features

- **Person generation controls** for image/video:
  - `dont_allow` — block all people
  - `allow_adult` — adults only (default)
  - `allow_all` — adults and children
- **SynthID watermark** on all generated media (automatic)

## Nanobot Implementation

Not implemented. No `safety_settings` in `GenerateContentConfig`.

Image generation uses `person_generation="allow_adult"` (hardcoded in creative.py) but chat has no safety configuration.

**What's needed:**
- Add safety settings to `GenerateContentConfig` in `gemini_provider.py`
- Optionally expose as config option in `schema.py`
