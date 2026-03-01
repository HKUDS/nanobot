# Image Understanding

> **Status: Implemented** — inline base64 images
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/image-understanding

## What It Is

Multimodal vision capabilities: image captioning, classification, visual Q&A, object detection, and segmentation. No specialized ML training needed.

## Gemini API Capabilities

- **Formats:** PNG, JPEG, WEBP, HEIC, HEIF
- **Input methods:** inline base64, Files API, multiple images (up to 3,600 per request)
- **Object detection** — bounding boxes with 0–1000 coordinate system, custom labels
- **Segmentation** (2.5+) — contour masks with probability maps
- **OCR** — text extraction from images
- **Token cost:** 258 tokens for images <=384px; tiled at 768x768 for larger
- **Media resolution control** — `media_resolution` parameter for token/detail tradeoff

## Nanobot Implementation

**File:** `scorpion/providers/gemini_provider.py` (lines 162-189)

```python
@staticmethod
def _user_content_to_parts(content):
    # Handles base64 inline images: data:image/png;base64,...
    if url_data.startswith("data:"):
        header, _, b64 = url_data.partition(",")
        mime = header.split(";")[0].split(":")[1]
        parts.append(types.Part(
            inline_data=types.Blob(mime_type=mime, data=base64.b64decode(b64)),
        ))
```

**What's implemented:**
- Base64 inline image input (data URIs)
- Auto MIME type detection from data URI header
- `types.Blob` + `types.Part(inline_data=...)` conversion

**What's missing:**
- Files API upload for images
- File URI references
- Object detection / bounding box requests
- Segmentation / contour mask requests
- `media_resolution` parameter
- Multiple image batch analysis
