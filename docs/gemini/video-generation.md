# Video Generation — Veo

> **Status: Implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/video

## What It Is

State-of-the-art video generation with natively synchronized audio. Text-to-video, image-to-video, video extension, and frame interpolation.

## Gemini API Capabilities

### Models

| Model | Notes |
|-------|-------|
| `veo-3.1-generate-preview` | Latest, with synchronized audio |
| Veo 3.1 Fast | Faster variant |
| Veo 3 / Veo 3 Fast | Earlier versions |

### Features

- **Text-to-video** with synchronized audio (dialogue, SFX, ambient)
- **Image-to-video** — animate a still frame
- **Video extension** — add 7s per extension, up to 20 times
- **Frame interpolation** — generate video between first and last frames
- **Reference images** — up to 3 for style/content guidance
- **Negative prompts** — specify unwanted content
- **Seed** for reproducibility

### Parameters

| Param | Options |
|-------|---------|
| Duration | 4, 6, or 8 seconds |
| Resolution | 720p, 1080p, 4K |
| Aspect ratio | 16:9, 9:16 |

### Operation

- Async long-running operation (11s–6min)
- Polling via `operations.get()` until `done`
- 2-day server storage for generated videos
- SynthID watermark on all output

## Nanobot Implementation

**File:** `scorpion/agent/tools/creative.py` (lines 157-253)

```python
# Lines 221-249: Video generation with polling
op = await client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt=prompt,
    config=types.GenerateVideosConfig(
        aspect_ratio=aspect_ratio,
        number_of_videos=1,
    ),
)
# Polling loop
while not op.done:
    await asyncio.sleep(10)
    op = await client.operations.get(operation=op)
# Download
video = op.response.generated_videos[0]
await client.files.download(file=video.video, download_config=...)
```

**What's implemented:**
- `veo-3.1-generate-preview` model
- Text-to-video generation
- Aspect ratio (16:9, 9:16)
- Resolution (720p, 1080p)
- Async polling loop (10s intervals)
- File download via `client.files.download()`
- MP4 output to workspace

**What's missing:**
- Image-to-video (animate still frame)
- Video extension (extend existing video)
- Frame interpolation
- Reference images
- Negative prompts
- Duration control (4/6/8s) — not exposed as tool parameter
- 4K resolution option
- Seed for reproducibility
