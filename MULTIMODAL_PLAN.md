# Multi-modal Support Implementation Plan

**GitHub Issue**: #223
**Branch**: `feature/multimodal-support`
**Status**: Planning Phase

---

## Table of Contents
1. [Overview](#overview)
2. [Current State Analysis](#current-state-analysis)
3. [Design Principles](#design-principles)
4. [Phase 1: Image/Vision Support](#phase-1-imagevision-support)
5. [Phase 2: Voice/TTS Support](#phase-2-voicetts-support)
6. [Phase 3: Video Support](#phase-3-video-support)
7. [Testing Strategy](#testing-strategy)
8. [Configuration Schema](#configuration-schema)

---

## Overview

This plan implements multi-modal capabilities for nanobot to process and generate images, voice, and video content. The implementation follows nanobot's ultra-lightweight philosophy (~4,000 lines target) and leverages provider-native APIs without adding heavy ML dependencies.

### Scope Summary

| Phase | Capability | Status |
|-------|-----------|--------|
| **Phase 1** | Image/Vision | NEW |
| **Phase 2** | Text-to-Speech (TTS) | NEW |
| **Phase 3** | Video Analysis | NEW |

---

## Current State Analysis

### What Already Exists

1. **Image Handling Infrastructure** (`nanobot/agent/context.py:161-177`)
   - `_build_user_content()` method already converts images to base64
   - Supports OpenAI-style image_url format: `data:{mime};base64,{b64}`
   - **Gap**: LiteLLM provider doesn't pass images to non-OpenAI models

2. **Media Download** (`nanobot/channels/telegram.py:222-269`)
   - Downloads photos, voice, audio, documents
   - Saves to `~/.nanobot/media/`
   - Transcribes voice using Groq Whisper
   - **Gap**: Images are downloaded but only passed as text paths, not as vision content

3. **Voice Transcription** (`nanobot/providers/transcription.py`)
   - `GroqTranscriptionProvider` for speech-to-text
   - **Gap**: No text-to-speech (TTS) for voice output

4. **Message Flow** (`nanobot/agent/loop.py:176-183`)
   - Media is passed from `InboundMessage` → `ContextBuilder.build_messages()`
   - **Gap**: Outbound messages don't support media attachments

### Architecture Diagram

```
┌─────────────────┐
│  Telegram/WhatsApp │
│  (media upload)  │
└────────┬─────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    BaseChannel._handle_message()            │
│  • Downloads media to ~/.nanobot/media/                      │
│  • Creates InboundMessage(content, media=[paths])           │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    AgentLoop._process_message()             │
│  • Gets session history                                     │
│  • Calls ContextBuilder.build_messages(history, content, media) │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              ContextBuilder._build_user_content()           │
│  • Converts images to base64 data URLs                      │
│  • Returns: [image_url, ..., text]                          │
│  • ⚠️ CURRENT: Only works for OpenAI format                 │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              LiteLLMProvider.chat()                         │
│  • ⚠️ MISSING: Claude/Gemini vision support                 │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    OutboundMessage                          │
│  • ⚠️ MISSING: TTS output for voice                         │
│  • ⚠️ MISSING: Image generation                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Design Principles

1. **Ultra-Lightweight**: No heavy ML libraries (no torch, transformers, etc.)
2. **Provider-Native APIs**: Use Claude Vision, GPT-4V, Gemini Pro Vision directly
3. **Optional by Default**: Multi-modal features disabled unless configured
4. **Consistent Patterns**: Follow existing `GroqTranscriptionProvider` pattern
5. **Channel Agnostic**: Work across Telegram, WhatsApp, Discord, CLI

---

## Phase 1: Image/Vision Support

### Goal

Enable the LLM to "see" and analyze images from users.

### Changes Required

#### 1.1 LiteLLMProvider - Add Vision Support

**File**: `nanobot/providers/litellm_provider.py`

**Current Issue**: The provider doesn't handle vision content for Claude/Gemini.

**Solution**: Extend the `chat()` method to:
- Detect if messages contain image content
- Format images appropriately for each provider:
  - **Claude**: `{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}`
  - **Gemini**: `{"role": "user", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": "..."}}]}`
  - **OpenAI/OpenRouter**: Already supported via `image_url` format

```python
# New method to add
def _format_content_for_provider(self, content: Any, model: str) -> Any:
    """
    Format message content for specific provider's multimodal format.

    Args:
        content: Message content (str or list with images)
        model: Model name to determine format

    Returns:
        Formatted content for the provider
    """
    # Handle text-only
    if isinstance(content, str):
        return content

    # Handle multimodal content
    if "claude" in model.lower() or "anthropic" in model.lower():
        return self._format_for_claude(content)
    elif "gemini" in model.lower():
        return self._format_for_gemini(content)
    else:
        # Default to OpenAI format
        return content

def _format_for_claude(self, content: list) -> list:
    """Format content for Claude vision API."""
    formatted = []
    for item in content:
        if item.get("type") == "image_url":
            # Parse data URL
            url = item["image_url"]["url"]
            if url.startswith("data:"):
                mime, b64 = url[5:].split(";base64,", 1)
                formatted.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64
                    }
                })
        elif item.get("type") == "text":
            formatted.append({"type": "text", "text": item["text"]})
    return formatted

def _format_for_gemini(self, content: list) -> list:
    """Format content for Gemini vision API."""
    parts = []
    for item in content:
        if item.get("type") == "image_url":
            url = item["image_url"]["url"]
            if url.startswith("data:"):
                mime, b64 = url[5:].split(";base64,", 1)
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64
                    }
                })
        elif item.get("type") == "text":
            parts.append({"text": item["text"]})
    return parts
```

#### 1.2 ContextBuilder - Ensure Images Pass Through

**File**: `nanobot/agent/context.py`

**Current State**: Already handles image encoding correctly (lines 161-177)

**Verification Needed**: Ensure the format matches provider expectations.

**Potential Enhancement**: Add image size limits and validation.

```python
# Add to ContextBuilder class
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB

def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
    """Build user message content with optional base64-encoded images."""
    if not media:
        return text

    images = []
    for path in media:
        p = Path(path)
        mime, _ = mimetypes.guess_type(path)
        if not p.is_file() or not mime or not mime.startswith("image/"):
            continue

        # Check file size
        if p.stat().st_size > self.MAX_IMAGE_SIZE:
            logger.warning(f"Image too large, skipping: {path}")
            continue

        b64 = base64.b64encode(p.read_bytes()).decode()
        images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    if not images:
        return text
    return images + [{"type": "text", "text": text}]
```

#### 1.3 Channel Media Handling - Verify Image Paths

**File**: `nanobot/channels/telegram.py`

**Current State**: Lines 225-227 handle photo downloads

**Verification**: Ensure image paths are passed correctly in the `media` parameter.

Already implemented at line 281: `media=media_paths`

#### 1.4 WhatsApp Channel - Add Image Support

**File**: `nanobot/channels/whatsapp.py`

**Current State**: Need to verify if WhatsApp bridge supports image downloads.

**Action**: Check `bridge/` TypeScript code for image handling.

#### 1.5 Configuration - Add Vision Settings

**File**: `nanobot/config/schema.py`

**Add**:
```python
class MultimodalConfig(BaseModel):
    """Multi-modal capabilities configuration."""
    vision_enabled: bool = True  # Enable image analysis
    max_image_size: int = 20 * 1024 * 1024  # 20MB default

class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    multimodal: MultimodalConfig = Field(default_factory=MultimodalConfig)
    restrict_to_workspace: bool = False
```

---

## Phase 2: Voice/TTS Support

### Goal

Enable nanobot to speak responses back to users (text-to-speech).

### Changes Required

#### 2.1 TTS Provider - New File

**File**: `nanobot/providers/tts.py` (NEW)

**Design**: Follow the pattern of `GroqTranscriptionProvider`

```python
"""Text-to-speech provider using multiple backends."""

import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class TTSProvider:
    """
    Text-to-speech provider supporting multiple backends.

    Supports: Groq, OpenAI, ElevenLabs
    """

    def __init__(
        self,
        provider: str = "groq",  # groq, openai, elevenlabs
        api_key: str | None = None,
        voice: str | None = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.voice = voice or self._default_voice(provider)

    def _default_voice(self, provider: str) -> str:
        """Get default voice for provider."""
        return {
            "groq": "en-US-JennyNeural",  # Or equivalent
            "openai": "alloy",
            "elevenlabs": "21m00Tcm4TlvDq8ikWAM",
        }.get(provider, "alloy")

    async def synthesize(self, text: str, output_path: str | Path) -> bool:
        """
        Convert text to speech.

        Args:
            text: Text to synthesize.
            output_path: Where to save the audio file.

        Returns:
            True if successful, False otherwise.
        """
        if self.provider == "groq":
            return await self._synthesize_groq(text, output_path)
        elif self.provider == "openai":
            return await self._synthesize_openai(text, output_path)
        elif self.provider == "elevenlabs":
            return await self._synthesize_elevenlabs(text, output_path)
        else:
            logger.error(f"Unknown TTS provider: {self.provider}")
            return False

    async def _synthesize_groq(self, text: str, output_path: Path) -> bool:
        """Synthesize using Groq (if they add TTS)."""
        # Note: Groq may not have TTS yet, check their API
        logger.warning("Groq TTS not yet available, falling back to OpenAI")
        return await self._synthesize_openai(text, output_path)

    async def _synthesize_openai(self, text: str, output_path: Path) -> bool:
        """Synthesize using OpenAI's TTS API."""
        if not self.api_key:
            logger.error("OpenAI API key not configured for TTS")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "tts-1",
                        "input": text,
                        "voice": self.voice,
                    },
                    timeout=60.0
                )
                response.raise_for_status()

                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(response.content)

                logger.info(f"TTS audio saved to {output_path}")
                return True
        except Exception as e:
            logger.error(f"OpenAI TTS error: {e}")
            return False

    async def _synthesize_elevenlabs(self, text: str, output_path: Path) -> bool:
        """Synthesize using ElevenLabs."""
        # Implementation for ElevenLabs
        pass
```

#### 2.2 Channel Integration - Send Voice Messages

**File**: `nanobot/channels/telegram.py`

**Add method**:
```python
async def send_voice(self, chat_id: int, audio_path: str) -> None:
    """Send a voice message to Telegram."""
    if not self._app:
        logger.warning("Telegram bot not running")
        return

    try:
        with open(audio_path, "rb") as f:
            await self._app.bot.send_voice(
                chat_id=chat_id,
                voice=f
            )
    except Exception as e:
        logger.error(f"Failed to send voice message: {e}")
```

**Modify `send()` method**:
```python
async def send(self, msg: OutboundMessage) -> None:
    """Send a message through Telegram."""
    if not self._app:
        logger.warning("Telegram bot not running")
        return

    try:
        chat_id = int(msg.chat_id)

        # Check if voice output is requested
        if msg.metadata.get("voice"):
            # Synthesize and send voice
            tts = self.tts_provider  # Injected in __init__
            audio_path = Path.home() / ".nanobot" / "media" / f"{msg.chat_id}_voice.ogg"
            if await tts.synthesize(msg.content, audio_path):
                await self.send_voice(chat_id, str(audio_path))
                return

        # Regular text message
        html_content = _markdown_to_telegram_html(msg.content)
        await self._app.bot.send_message(
            chat_id=chat_id,
            text=html_content,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
```

#### 2.3 AgentLoop - TTS Configuration

**File**: `nanobot/agent/loop.py`

**Add TTS provider to initialization**:
```python
def __init__(
    self,
    # ... existing params ...
    tts_provider: TTSProvider | None = None,
):
    # ... existing code ...
    self.tts_provider = tts_provider
```

#### 2.4 Voice Command - User Control

**New Tool**: `nanobot/agent/tools/voice.py`

```python
"""Tool for controlling TTS output."""

from nanobot.agent.tools.base import Tool


class VoiceTool(Tool):
    """Enable/disable voice output."""

    name = "voice"
    description = "Enable or disable text-to-speech output for responses. Use: voice(on) or voice(off)"

    def __init__(self, state_callback):
        self.state_callback = state_callback

    async def execute(self, state: str) -> str:
        """Toggle voice output."""
        if state.lower() in ("on", "enabled", "true"):
            await self.state_callback(True)
            return "Voice output enabled."
        elif state.lower() in ("off", "disabled", "false"):
            await self.state_callback(False)
            return "Voice output disabled."
        else:
            return f"Unknown voice state: {state}. Use 'on' or 'off'."
```

#### 2.5 Configuration Schema

**File**: `nanobot/config/schema.py`

**Add**:
```python
class TTSConfig(BaseModel):
    """Text-to-speech configuration."""
    enabled: bool = False
    provider: str = "openai"  # openai, elevenlabs
    voice: str = "alloy"  # openai: alloy, echo, fable, onyx, nova, shimmer
    api_key: str = ""  # Optional override

class MultimodalConfig(BaseModel):
    """Multi-modal capabilities configuration."""
    vision_enabled: bool = True
    max_image_size: int = 20 * 1024 * 1024
    tts: TTSConfig = Field(default_factory=TTSConfig)
```

---

## Phase 3: Video Support

### Goal

Enable analysis of video content through frame extraction and captioning.

### Approach

1. **Frame Extraction**: Extract key frames from video using `ffmpeg`
2. **Image Analysis**: Pass frames through vision API (Phase 1)
3. **Audio Transcription**: Extract audio and transcribe (existing)

### Changes Required

#### 3.1 Video Processor - New File

**File**: `nanobot/agent/video.py` (NEW)

```python
"""Video processing utilities."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class VideoProcessor:
    """
    Extract frames and audio from videos for analysis.

    Uses ffmpeg for processing (must be installed).
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.media_dir = workspace.parent / "media"
        self.frames_dir = self.media_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    async def extract_key_frames(
        self,
        video_path: str | Path,
        max_frames: int = 5,
    ) -> list[str]:
        """
        Extract key frames from a video file.

        Args:
            video_path: Path to video file.
            max_frames: Maximum number of frames to extract.

        Returns:
            List of paths to extracted frame images.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return []

        output_prefix = self.frames_dir / f"{video_path.stem}_frame"

        # Extract frames at 1fps, max N frames
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"fps=1/10,scale=320:-1",  # 1 frame every 10 sec
            "-vframes", str(max_frames),
            "-y",  # Overwrite
            f"{output_prefix}_%01d.jpg"
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"ffmpeg error: {stderr.decode()}")
                return []

            # Find extracted frames
            frames = []
            for i in range(1, max_frames + 1):
                frame_path = Path(f"{output_prefix}_{i}.jpg")
                if frame_path.exists():
                    frames.append(str(frame_path))
                else:
                    break

            logger.info(f"Extracted {len(frames)} frames from {video_path.name}")
            return frames

        except FileNotFoundError:
            logger.error("ffmpeg not found. Install with: apt install ffmpeg or brew install ffmpeg")
            return []
        except Exception as e:
            logger.error(f"Frame extraction error: {e}")
            return []

    async def extract_audio(self, video_path: str | Path) -> Path | None:
        """
        Extract audio track from video for transcription.

        Args:
            video_path: Path to video file.

        Returns:
            Path to extracted audio file, or None if no audio.
        """
        video_path = Path(video_path)
        output_path = self.media_dir / f"{video_path.stem}_audio.mp3"

        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",  # No video
            "-acodec", "libmp3lame",
            "-y",
            str(output_path)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            if process.returncode == 0 and output_path.exists():
                logger.info(f"Extracted audio to {output_path}")
                return output_path
            return None

        except Exception as e:
            logger.error(f"Audio extraction error: {e}")
            return None
```

#### 3.2 Channel Integration - Video Handling

**File**: `nanobot/channels/telegram.py`

**Modify `_on_message()`** to handle video:

```python
elif message.video:
    media_file = message.video
    media_type = "video"
```

**After download, extract frames**:
```python
if media_type == "video":
    from nanobot.agent.video import VideoProcessor
    processor = VideoProcessor(Path.home() / ".nanobot" / "workspace")
    frames = await processor.extract_key_frames(file_path, max_frames=3)
    media_paths.extend(frames)

    # Also extract audio for transcription
    audio_path = await processor.extract_audio(file_path)
    if audio_path:
        transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
        transcription = await transcriber.transcribe(audio_path)
        if transcription:
            content_parts.append(f"[video audio: {transcription}]")
```

#### 3.3 Configuration

```python
class MultimodalConfig(BaseModel):
    """Multi-modal capabilities configuration."""
    vision_enabled: bool = True
    max_image_size: int = 20 * 1024 * 1024
    max_video_frames: int = 5
    tts: TTSConfig = Field(default_factory=TTSConfig)
```

---

## Testing Strategy

### Unit Tests

1. **Vision Format Tests** (`tests/test_vision.py`)
   - Test Claude format conversion
   - Test Gemini format conversion
   - Test OpenAI format (existing)

2. **TTS Provider Tests** (`tests/test_tts.py`)
   - Mock API responses
   - Test file output
   - Test error handling

3. **Video Processor Tests** (`tests/test_video.py`)
   - Mock ffmpeg subprocess
   - Test frame extraction logic
   - Test audio extraction

### Integration Tests

1. **End-to-End Vision Test**
   ```bash
   # Send image via Telegram
   # Verify response includes image analysis
   ```

2. **TTS Loop Test**
   ```bash
   # Enable voice mode
   # Send message
   # Verify audio file sent back
   ```

3. **Video Analysis Test**
   ```bash
   # Send short video
   # Verify frame analysis
   # Verify transcription
   ```

### Manual Testing Checklist

- [ ] Send photo to Telegram bot → Analyze image content
- [ ] Send image with caption → Analyze both
- [ ] Enable voice mode → Receive audio response
- [ ] Send video → Get frame analysis
- [ ] Send video with audio → Get transcription
- [ ] Test with Claude (vision)
- [ ] Test with GPT-4V
- [ ] Test with Gemini Pro Vision

---

## Configuration Schema

### Complete `config.json` Example

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    },
    "openai": {
      "apiKey": "sk-xxx"
    },
    "groq": {
      "apiKey": "gsk_xxx"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "BSA-xxx"
      }
    },
    "multimodal": {
      "vision_enabled": true,
      "max_image_size": 20971520,
      "max_video_frames": 5,
      "tts": {
        "enabled": false,
        "provider": "openai",
        "voice": "alloy",
        "apiKey": ""
      }
    }
  }
}
```

---

## Implementation Order

### Priority 1: Vision (Week 1)
1. LiteLLMProvider vision format conversion
2. ContextBuilder validation
3. Test with Claude/Gemini
4. Documentation update

### Priority 2: TTS (Week 2)
1. TTSProvider implementation
2. Channel integration (Telegram)
3. Voice tool
4. Test voice output

### Priority 3: Video (Week 3)
1. VideoProcessor implementation
2. Channel video handling
3. Frame extraction tests
4. Integration test

---

## Open Questions

1. **ElevenLabs Integration**: Should we prioritize ElevenLabs over OpenAI for TTS?
2. **Image Generation**: Should we add DALL-E/Image generation as part of this?
3. **Video Playback**: Should we support sending video files back to users?
4. **Memory Limits**: Vision tokens are expensive - should we add token counting?
5. **ffmpeg Dependency**: Should we make ffmpeg optional or required?

---

## References

- [LiteLLM Multimodal Docs](https://docs.litellm.ai/docs/providers/multimodal)
- [Claude Vision API](https://docs.anthropic.com/en/docs/vision)
- [OpenAI Vision](https://platform.openai.com/docs/guides/vision)
- [Gemini Pro Vision](https://ai.google.dev/gemini-api/docs/vision)
- [Telegram Bot API - Photos](https://core.telegram.org/bots/api#photosize)
- [Telegram Bot API - Voice](https://core.telegram.org/bots/api#voice)
