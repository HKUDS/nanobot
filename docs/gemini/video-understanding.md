# Video Understanding

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/video-understanding

## What It Is

Process and analyze video content: describe scenes, answer questions, extract information, reference timestamps. Analyzes both audio and visual streams simultaneously.

## Gemini API Capabilities

- **Formats:** MP4, MPEG, MOV, AVI, FLV, MPG, WEBM, WMV, 3GPP
- **Duration:** up to 1 hour (default res) or 3 hours (low res) with 1M context window
- **Sampling:** 1 FPS default (configurable)
- **Timestamp queries:** `MM:SS` format for specific moments
- **Audio + visual** analyzed simultaneously
- **YouTube URLs** supported (public videos)
- **Token cost:** ~263 tokens/second (default) or ~100 tokens/second (low res)
- **Input methods:** Files API (recommended for >100MB), Cloud Storage, inline data (<100MB), YouTube URLs
- **Video clipping:** start/end offsets via `videoMetadata`
- **Custom frame rates** for high-motion or static content
- **Max file size:** 20GB (paid) / 2GB (free) via Files API

## Nanobot Implementation

Not implemented. The message converter in `gemini_provider.py` only handles text and image content types. No video input parts are constructed.

Video generation (Veo) exists but video *understanding* (analyzing existing videos) is not wired.

**What's needed:**
- Accept video file/URL inputs in chat messages
- Upload via Files API for large files
- Construct `types.Part(file_data=...)` for video content
- Support timestamp-based queries
