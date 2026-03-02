"""Built-in creative tools: image, video, and music generation via Google AI."""

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
        cfg = load_config()
        return getattr(getattr(cfg.providers, "gemini", None), "api_key", None) or ""
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
                    "description": "Description of the image to generate",
                },
                "model": {
                    "type": "string",
                    "description": "Model: imagen4 (default, photorealistic), imagen4-fast, gemini (context-aware)",
                    "enum": ["imagen4", "imagen4-fast", "imagen4-ultra", "gemini"],
                },
                "aspect": {
                    "type": "string",
                    "description": "Aspect ratio (default: 1:1)",
                    "enum": ["1:1", "16:9", "9:16", "3:4", "4:3"],
                },
                "count": {
                    "type": "integer",
                    "description": "Number of images (1-4, default: 1)",
                    "minimum": 1,
                    "maximum": 4,
                },
            },
            "required": ["prompt"],
        }

    async def execute(
        self,
        prompt: str,
        model: str = "imagen4",
        aspect: str = "1:1",
        count: int = 1,
        **kwargs: Any,
    ) -> str:
        api_key = _get_gemini_key()
        if not api_key:
            return "Error: GEMINI_API_KEY not configured. Set it in ~/.nanobot/config.json under providers.gemini.api_key"

        out_dir = _MEDIA_ROOT / "images"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            if model == "gemini":
                return await self._gemini_image(client, types, prompt, aspect, out_dir)

            model_map = {
                "imagen4": "imagen-4.0-generate-001",
                "imagen4-fast": "imagen-4.0-fast-generate-001",
                "imagen4-ultra": "imagen-4.0-ultra-generate-001",
            }
            model_id = model_map.get(model, "imagen-4.0-generate-001")

            response = client.models.generate_images(
                model=model_id,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=count,
                    aspect_ratio=aspect,
                    person_generation="allow_adult",
                ),
            )

            paths = []
            for i, img in enumerate(response.generated_images):
                suffix = f"_{i}" if count > 1 else ""
                out_path = out_dir / f"image_{_ts()}{suffix}.png"
                out_path.write_bytes(img.image.image_bytes)
                paths.append(str(out_path))
                logger.info("Generated image: {}", out_path)

            return "\n".join(paths) if paths else "Error: No images generated"

        except Exception as e:
            logger.error("Image generation failed: {}", e)
            return f"Error generating image: {e}"

    @staticmethod
    async def _gemini_image(client, types, prompt: str, aspect: str, out_dir: Path) -> str:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        paths = []
        ts = _ts()
        idx = 0
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                ext = part.inline_data.mime_type.split("/")[-1]
                if ext == "jpeg":
                    ext = "jpg"
                suffix = f"_{idx}" if idx > 0 else ""
                out_path = out_dir / f"image_{ts}{suffix}.{ext}"
                out_path.write_bytes(part.inline_data.data)
                paths.append(str(out_path))
                logger.info("Generated image: {}", out_path)
                idx += 1
        return "\n".join(paths) if paths else "Error: No images generated"


# ── Video Generation ──────────────────────────────────────────────────────────


class GenerateVideoTool(Tool):
    """Non-blocking video generation.

    Uses a subagent (via SubagentManager) when available so the main loop
    stays responsive — returns immediately with a "generating..." message
    then delivers the result when the subagent completes.

    Falls back to blocking generation in CLI mode.
    """

    def __init__(self, subagent_manager=None):
        self._manager = subagent_manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "generate_video"

    @property
    def description(self) -> str:
        return (
            "Generate videos using Google Veo 3.1. Takes 1-5 minutes. "
            "Returns immediately — video is generated in the background and "
            "delivered when ready. Tip: wrap dialogue in quotes for AI audio."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Description of the video to generate",
                },
                "duration": {
                    "type": "integer",
                    "description": "Duration in seconds (4, 6, or 8, default: 8)",
                    "enum": [4, 6, 8],
                },
                "aspect": {
                    "type": "string",
                    "description": "Aspect ratio (default: 16:9)",
                    "enum": ["16:9", "9:16"],
                },
                "resolution": {
                    "type": "string",
                    "description": "Resolution (default: 720p)",
                    "enum": ["720p", "1080p"],
                },
            },
            "required": ["prompt"],
        }

    async def execute(
        self,
        prompt: str,
        duration: int = 8,
        aspect: str = "16:9",
        resolution: str = "720p",
        **kwargs: Any,
    ) -> str:
        api_key = _get_gemini_key()
        if not api_key:
            return "Error: GEMINI_API_KEY not configured."

        # Non-blocking path: delegate to subagent if manager is available
        if self._manager is not None:
            task_desc = (
                f"Generate a video with Google Veo 3.1 and send it to the user.\n"
                f"Prompt: {prompt}\n"
                f"Duration: {duration}s, Aspect: {aspect}, Resolution: {resolution}\n"
                f"Save to ~/.nanobot/media/videos/ and send via message tool with media=[path]."
            )
            try:
                await self._manager.spawn(
                    task=task_desc,
                    label=f"video: {prompt[:40]}",
                    origin_channel=self._origin_channel,
                    origin_chat_id=self._origin_chat_id,
                )
                return (
                    f"🎬 Video generation started in the background. "
                    f"This takes 1–5 minutes — I'll send it when it's ready."
                )
            except Exception as e:
                logger.warning("Subagent spawn failed, falling back to blocking: {}", e)

        # Blocking fallback (CLI or no subagent manager)
        return await _generate_video_blocking(prompt, duration, aspect, resolution, api_key)


async def _generate_video_blocking(
    prompt: str,
    duration: int,
    aspect: str,
    resolution: str,
    api_key: str,
) -> str:
    """Blocking Veo 3.1 generation — used in CLI mode."""
    out_dir = _MEDIA_ROOT / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        logger.info(
            "[VideoGen] Starting Veo 3.1 — prompt={!r} duration={}s aspect={} res={}",
            prompt[:80], duration, aspect, resolution,
        )

        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=aspect,
                duration_seconds=duration,
                resolution=resolution,
                number_of_videos=1,
            ),
        )

        # Poll until complete
        while not operation.done:
            await asyncio.sleep(10)
            operation = client.operations.get(operation)

        videos = operation.result.generated_videos
        if not videos:
            return "Error: No video generated"

        out_path = out_dir / f"video_{_ts()}.mp4"
        out_path.write_bytes(videos[0].video.video_bytes)
        logger.info("[VideoGen] Saved: {}", out_path)
        return str(out_path)

    except Exception as e:
        logger.error("[VideoGen] Failed: {}", e)
        return f"Error generating video: {e}"


# ── Music Generation ──────────────────────────────────────────────────────────


_SAMPLE_RATE = 48000
_CHANNELS = 2
_SAMPLE_WIDTH = 2  # 16-bit


class GenerateMusicTool(Tool):

    @property
    def name(self) -> str:
        return "generate_music"

    @property
    def description(self) -> str:
        return (
            "Generate instrumental music using Google Lyria RealTime. "
            "Returns the file path of the generated WAV. Always instrumental (no vocals)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Music style/mood description (e.g. 'upbeat jazz piano', 'ambient techno')",
                },
                "duration": {
                    "type": "integer",
                    "description": "Duration in seconds (default: 30)",
                    "minimum": 5,
                    "maximum": 120,
                },
                "bpm": {
                    "type": "integer",
                    "description": "Beats per minute, 60-200 (default: auto)",
                    "minimum": 60,
                    "maximum": 200,
                },
            },
            "required": ["prompt"],
        }

    async def execute(
        self,
        prompt: str,
        duration: int = 30,
        bpm: int | None = None,
        **kwargs: Any,
    ) -> str:
        api_key = _get_gemini_key()
        if not api_key:
            return "Error: GEMINI_API_KEY not configured."

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

            logger.info("Starting music generation: {} ({}s)", prompt, duration)
            audio_chunks: list[bytes] = []
            collected = 0

            async with client.aio.live.music.connect(model="models/lyria-realtime-exp") as session:
                await session.set_weighted_prompts(
                    prompts=[types.WeightedPrompt(text=prompt, weight=1.0)]
                )

                config_kwargs: dict[str, Any] = dict(
                    density=0.5, brightness=0.5, guidance=4.0, temperature=1.0,
                )
                if bpm is not None:
                    config_kwargs["bpm"] = bpm

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

            if not audio_chunks:
                return "Error: No audio received from Lyria"

            pcm_data = b"".join(audio_chunks)
            out_path = out_dir / f"music_{_ts()}.wav"
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(_CHANNELS)
                wf.setsampwidth(_SAMPLE_WIDTH)
                wf.setframerate(_SAMPLE_RATE)
                wf.writeframes(pcm_data)

            logger.info("Generated music: {} ({}s)", out_path, collected // bytes_per_sec)
            return str(out_path)

        except Exception as e:
            logger.error("Music generation failed: {}", e)
            return f"Error generating music: {e}"
