# Video Generation Fixes

## Overview

This document describes the fixes applied to the video generation functionality in scorpion. The changes fix critical bugs where user-specified parameters were not being passed to the Google Veo API, and add new video understanding capabilities.

---

## Critical Bug Fixes

### 1. Missing Duration Parameter

**Problem:** The `duration` parameter accepted by the video generation tool was never passed to the Veo API. All videos were generated with the default duration regardless of user input.

**Files Fixed:**
- `scorpion/agent/tools/creative.py` (line 268-273)
- `scorpion/adk/tools.py` (line 788-794)

**Before:**
```python
config=types.GenerateVideosConfig(
    aspect_ratio=aspect,
    resolution=resolution,
    number_of_videos=1,
)
```

**After:**
```python
config=types.GenerateVideosConfig(
    aspect_ratio=aspect,
    duration_seconds=duration,  # ✓ Now included
    resolution=resolution,
    number_of_videos=1,
)
```

**Impact:** Users can now specify video duration (4, 6, or 8 seconds) and the API will respect it.

---

### 2. Code Consolidation

**Problem:** Video generation logic was duplicated in two places:
- `GenerateVideoTool` class in `creative.py`
- `generate_video()` function in `adk/tools.py`

This created maintenance burden and potential for inconsistencies.

**Solution:** Refactored `GenerateVideoTool.execute()` to delegate to the shared `generate_video()` function.

**Before (creative.py):**
```python
async def execute(self, prompt: str, duration: int = 8, ...):
    # 80+ lines of duplicate video generation logic
    api_key = _get_gemini_key()
    # ... full implementation ...
```

**After (creative.py):**
```python
async def execute(self, prompt: str, duration: int = 8, ...):
    from scorpion.adk.tools import generate_video
    from google.adk.tools import ToolContext
    
    tool_context = ToolContext(state={...})
    return await generate_video(
        prompt=prompt,
        duration=duration,
        aspect=aspect,
        resolution=resolution,
        tool_context=tool_context,
    )
```

**Impact:** Single source of truth for video generation logic, easier maintenance.

---

## New Features

### 3. Video Understanding (Analysis)

**Problem:** Users could not upload existing videos for analysis. The Gemini provider only handled text and images.

**Solution:** Enhanced `gemini_provider.py` with full video file support.

**Changes Made:**

#### a. File Upload Support (`_upload_video_files()`)
```python
async def _upload_video_files(self, messages: list[dict[str, Any]]) -> None:
    """Upload video files to Gemini Files API and replace file paths with URIs."""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and content.endswith((".mp4", ".mov", ...)):
            uploaded = await self._upload_file(content)
            msg["content"] = f"gemini-file://{uploaded.name}"
```

#### b. Enhanced Content Parsing (`_user_content_to_parts()`)

Now supports:
- **Video file paths**: `"video.mp4"` → auto-detected and uploaded
- **YouTube URLs**: `"https://youtube.com/watch?v=..."` → passed as file data
- **Video blocks**: `{"type": "video_file", "file_path": "..."}` 
- **Video URLs**: `{"type": "video_url", "video_url": {"url": "..."}}`
- **Base64 inline video**: `data:video/mp4;base64,...`

**Example Usage:**

```python
# Direct file path in chat
await agent.chat("Analyze this video: /path/to/video.mp4")

# Structured video block
await agent.chat([{
    "type": "video_file",
    "file_path": "/path/to/video.mp4"
}])

# YouTube URL
await agent.chat("Summarize this: https://youtube.com/watch?v=abc123")
```

**Impact:** Users can now upload videos for AI analysis, summarization, and Q&A.

---

## Technical Details

### Supported Video Formats

| Format | Extensions | Use Case |
|--------|-----------|----------|
| Video Generation | N/A (AI-generated) | Create new videos from text prompts |
| Video Understanding | `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm` | Analyze existing videos |
| YouTube URLs | `youtube.com`, `youtu.be` | Analyze online videos |

### Veo 3.1 API Parameters

| Parameter | Type | Values | Default | Status |
|-----------|------|--------|---------|--------|
| `prompt` | string | Any text description | Required | ✓ Fixed |
| `duration_seconds` | integer | 4, 6, 8 | 8 | ✓ Fixed |
| `aspect_ratio` | string | "16:9", "9:16" | "16:9" | ✓ Working |
| `resolution` | string | "720p", "1080p" | "720p" | ✓ Working |
| `number_of_videos` | integer | 1-4 | 1 | ✓ Working |

### File Locations

- **Generated videos**: `~/.scorpion/media/videos/video_YYYYMMDD_HHMMSS.mp4`
- **Generated images**: `~/.scorpion/media/images/image_YYYYMMDD_HHMMSS.png`
- **Generated music**: `~/.scorpion/media/music/music_YYYYMMDD_HHMMSS.wav`

---

## Testing

### Test Video Generation

```bash
# Start the agent
scorpion agent -m "Generate a 4-second video of a cat walking in 9:16 aspect ratio"

# Or use the tool directly in interactive mode
You: generate_video(prompt="A sunset over the ocean", duration=6, aspect="16:9", resolution="1080p")
```

### Test Video Understanding

```bash
# Upload a video file for analysis
scorpion agent -m "Analyze this video: /path/to/my/video.mp4"

# Or ask questions about a video
scorpion agent -m "What happens in this video? /path/to/video.mov"

# YouTube URL support
scorpion agent -m "Summarize this video: https://youtube.com/watch?v=..."
```

---

## Known Limitations

### Video Generation
- ❌ Image-to-video (animate still frames) - Not implemented
- ❌ Video extension (extend existing videos) - Not implemented
- ❌ Frame interpolation - Not implemented
- ❌ Reference images - Not implemented
- ❌ Negative prompts - Not implemented
- ❌ Seed for reproducibility - Not implemented
- ❌ 4K resolution - API supports but not exposed in tool

### Video Understanding
- ⚠️ Large video files (>2GB) may fail to upload
- ⚠️ Processing time scales with video length
- ⚠️ Some video codecs may not be supported by Gemini API

---

## Files Modified

| File | Changes | Lines Changed |
|------|---------|---------------|
| `scorpion/agent/tools/creative.py` | Fixed duration param, consolidated code | ~60 removed |
| `scorpion/adk/tools.py` | Fixed duration parameter | 1 |
| `scorpion/providers/gemini_provider.py` | Added video understanding | ~150 added |

---

## Changelog

### v0.1.4.post4 (2026-03-02)

**Fixed:**
- Video generation now correctly passes `duration_seconds` to Veo API
- Consolidated duplicate video generation code into single implementation

**Added:**
- Video file upload and analysis support
- YouTube URL support for video analysis
- Base64 inline video data support
- New `video_file` and `video_url` content block types

---

## Support

For issues or questions:
1. Check the [video-generation.md](docs/gemini/video-generation.md) documentation
2. Review [video-understanding.md](docs/gemini/video-understanding.md) for analysis features
3. Ensure Gemini API key has Veo access enabled
4. Verify video files are under 2GB for upload
