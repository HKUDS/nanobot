"""Creative media generation tools: image, video, and music via Google Gemini/Imagen APIs."""

from __future__ import annotations

import asyncio
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

_MEDIA_ROOT = Path.home() / ".nanobot" / "media"


def _get_gemini_key() -> str:
    """Resolve Gemini API key from config."""
    from nanobot.config.loader import load_config

    try:
        return load_config().providers.gemini.api_key or ""
    except Exception:
        return ""


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ── Image Generation ──────────────────────────────────────────────────────────


class GenerateImageTool(Tool):

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Generate images using Google Imagen 4 or Gemini. "
            "Returns the file path(s) of the generated image(s). "
            "Use the message tool with media=[path] to send the image to the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate",
                },
                "model": {
                    "type": "string",
                    "enum": ["imagen4", "imagen4-fast", "imagen4-ultra", "gemini"],
                    "description": (
                        "Model to use: 'imagen4' (default, photorealistic), "
                        "'imagen4-fast' (faster), 'imagen4-ultra' (highest quality), "
                        "'gemini' (context-aware, can edit/transform)"
                    ),
                },
                "aspect": {
                    "type": "string",
                    "enum": ["1:1", "16:9", "9:16", "3:4", "4:3"],
                    "description": "Aspect ratio (default: 1:1)",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 4,
                    "description": "Number of images to generate (1-4, default: 1)",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, **kwargs: Any) -> str:
        prompt = kwargs.get("prompt", "")
        model_choice = kwargs.get("model", "imagen4")
        aspect = kwargs.get("aspect", "1:1")
        count = kwargs.get("count", 1)

        api_key = _get_gemini_key()
        if not api_key:
            return (
                "Error: Gemini API key not configured. "
                "Set it in ~/.nanobot/config.json under providers.gemini.apiKey"
            )

        out_dir = _MEDIA_ROOT / "images"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            if model_choice == "gemini":
                return await self._generate_gemini(client, types, prompt, out_dir)

            model_map = {
                "imagen4": "imagen-4.0-generate-001",
                "imagen4-fast": "imagen-4.0-fast-generate-001",
                "imagen4-ultra": "imagen-4.0-ultra-generate-001",
            }
            model_id = model_map.get(model_choice, "imagen-4.0-generate-001")

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_images(
                    model=model_id,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=count,
                        aspect_ratio=aspect,
                        person_generation="allow_adult",
                    ),
                ),
            )

            if not response.generated_images:
                return "Error: No images were generated. The prompt may have been filtered."

            paths = []
            ts = _ts()
            for i, img in enumerate(response.generated_images):
                suffix = f"_{i + 1}" if count > 1 else ""
                out_path = out_dir / f"image_{ts}{suffix}.png"
                out_path.write_bytes(img.image.image_bytes)
                paths.append(str(out_path))
                logger.info("Generated image: {}", out_path)

            return "\n".join(paths)

        except Exception as e:
            logger.error("Image generation failed: {}", e)
            return f"Error generating image: {e}"

    async def _generate_gemini(self, client, types, prompt: str, out_dir: Path) -> str:
        """Generate image using Gemini's native image generation."""
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                ),
            ),
        )

        paths = []
        ts = _ts()
        for i, part in enumerate(response.candidates[0].content.parts):
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                ext = ".jpg" if "jpeg" in part.inline_data.mime_type else ".png"
                out_path = out_dir / f"gemini_{ts}_{i}{ext}"
                out_path.write_bytes(part.inline_data.data)
                paths.append(str(out_path))
                logger.info("Generated Gemini image: {}", out_path)

        if not paths:
            return "Error: Gemini did not return any images."
        return "\n".join(paths)


# ── Video Generation ──────────────────────────────────────────────────────────


class GenerateVideoTool(Tool):

    @property
    def name(self) -> str:
        return "generate_video"

    @property
    def description(self) -> str:
        return (
            "Generate a video using Google Veo. This takes 1-5 minutes. "
            "Returns the file path of the generated video. "
            "Use the message tool with media=[path] to send the video to the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the video to generate",
                },
                "duration": {
                    "type": "integer",
                    "enum": [4, 6, 8],
                    "description": "Duration in seconds (default: 8)",
                },
                "aspect": {
                    "type": "string",
                    "enum": ["16:9", "9:16"],
                    "description": "Aspect ratio (default: 16:9)",
                },
                "resolution": {
                    "type": "string",
                    "enum": ["720p", "1080p"],
                    "description": "Resolution (default: 720p)",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from nanobot.config.schema import VEO_MODEL

        prompt = kwargs.get("prompt", "")
        duration = kwargs.get("duration", 8)
        aspect = kwargs.get("aspect", "16:9")
        resolution = kwargs.get("resolution", "720p")

        api_key = _get_gemini_key()
        if not api_key:
            return (
                "Error: Gemini API key not configured. "
                "Set it in ~/.nanobot/config.json under providers.gemini.apiKey"
            )

        out_dir = _MEDIA_ROOT / "videos"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            logger.info("Starting video generation (this may take 1-5 minutes)...")

            operation = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_videos(
                    model=VEO_MODEL,
                    prompt=prompt,
                    config=types.GenerateVideosConfig(
                        aspect_ratio=aspect,
                        duration_seconds=duration,
                        resolution=resolution,
                        number_of_videos=1,
                    ),
                ),
            )

            # Poll for completion
            def _poll():
                while not operation.done:
                    time.sleep(10)
                    client.operations.get(operation)
                return operation

            op = await asyncio.get_event_loop().run_in_executor(None, _poll)

            video = op.response.generated_videos[0]
            client.files.download(file=video.video)

            ts = _ts()
            out_path = out_dir / f"video_{ts}.mp4"
            video.video.save(str(out_path))
            logger.info("Generated video: {}", out_path)

            return str(out_path)

        except Exception as e:
            error_msg = str(e)
            logger.error("Video generation failed: {}", e)
            if "503" in error_msg or "Service Unavailable" in error_msg:
                return (
                    "The video generation service is temporarily unavailable (503). "
                    "Please try again in a few minutes."
                )
            return f"Error generating video: {e}"


# ── Music Generation ──────────────────────────────────────────────────────────

_SAMPLE_RATE = 48000
_CHANNELS = 2
_SAMPLE_WIDTH = 2


class GenerateMusicTool(Tool):

    @property
    def name(self) -> str:
        return "generate_music"

    @property
    def description(self) -> str:
        return (
            "Generate music using Google Lyria. "
            "Returns the file path of the generated audio (WAV). "
            "Use the message tool with media=[path] to send the music to the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Music style/mood description "
                        "(e.g. 'upbeat jazz piano', 'ambient electronic', 'cinematic orchestral')"
                    ),
                },
                "duration": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 120,
                    "description": "Duration in seconds (5-120, default: 30)",
                },
                "bpm": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 200,
                    "description": "Beats per minute (60-200, optional — auto if omitted)",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from nanobot.config.schema import LYRIA_MODEL

        prompt = kwargs.get("prompt", "")
        duration = kwargs.get("duration", 30)
        bpm = kwargs.get("bpm")

        api_key = _get_gemini_key()
        if not api_key:
            return (
                "Error: Gemini API key not configured. "
                "Set it in ~/.nanobot/config.json under providers.gemini.apiKey"
            )

        out_dir = _MEDIA_ROOT / "music"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options={"api_version": "v1alpha"},
            )

            bytes_per_sec = _SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH
            target_bytes = duration * bytes_per_sec

            config_kwargs: dict[str, Any] = {
                "density": 0.5,
                "brightness": 0.5,
                "guidance": 4.0,
                "temperature": 1.0,
            }
            if bpm:
                config_kwargs["bpm"] = bpm

            audio_chunks: list[bytes] = []
            collected = 0

            async with client.aio.live.music.connect(model=LYRIA_MODEL) as session:
                await session.set_weighted_prompts(
                    prompts=[types.WeightedPrompt(text=prompt, weight=1.0)]
                )
                await session.set_music_generation_config(
                    config=types.LiveMusicGenerationConfig(**config_kwargs)
                )
                await session.play()

                async for message in session.receive():
                    try:
                        chunk = message.server_content.audio_chunks[0].data
                        if chunk:
                            audio_chunks.append(chunk)
                            collected += len(chunk)
                            if collected >= target_bytes:
                                await session.pause()
                                break
                    except (AttributeError, IndexError):
                        continue

            pcm_data = b"".join(audio_chunks)
            ts = _ts()
            out_path = out_dir / f"music_{ts}.wav"

            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(_CHANNELS)
                wf.setsampwidth(_SAMPLE_WIDTH)
                wf.setframerate(_SAMPLE_RATE)
                wf.writeframes(pcm_data)

            logger.info("Generated music: {} ({:.1f}s)", out_path, len(pcm_data) / bytes_per_sec)
            return str(out_path)

        except Exception as e:
            logger.error("Music generation failed: {}", e)
            return f"Error generating music: {e}"
