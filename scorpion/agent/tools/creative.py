"""Built-in creative tools: image, video, and music generation via Google AI."""

from __future__ import annotations

import asyncio
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from scorpion.agent.tools.base import Tool

_MEDIA_ROOT = Path.home() / ".scorpion" / "media"


def _get_gemini_key() -> str:
    """Resolve Gemini API key from config."""
    from scorpion.config.loader import load_config
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
            return "Error: GEMINI_API_KEY not configured"

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
            return f"Error: {e}"

    @staticmethod
    async def _gemini_image(client, types, prompt: str, aspect: str, out_dir: Path) -> str:
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
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
    """Non-blocking video generation tool.

    When a SubagentManager is provided, video generation is automatically
    offloaded to a background subagent so the main agent loop stays responsive.
    The subagent generates the video via Veo 3.1 and delivers it to the user
    via send_message with media attachment.
    """

    def __init__(self, subagent_manager=None):
        self._manager = subagent_manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """Update the routing context so the subagent knows where to deliver."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "generate_video"

    @property
    def description(self) -> str:
        return (
            "Generate videos using Google Veo 3.1. Takes 1-5 minutes. "
            "The video is generated in the background by a subagent and "
            "delivered to the user automatically when ready. "
            "Tip: wrap dialogue in quotes for AI-generated audio."
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
        # ToolContext cannot be constructed outside the ADK runner (it requires
        # an InvocationContext).  Call the generation logic directly instead.
        api_key = _get_gemini_key()
        if not api_key:
            return "Error: GEMINI_API_KEY not configured"

        # Non-blocking path: use background worker when the bus is active
        from scorpion.adk import tools as _adk_tools
        if _adk_tools._pending_results is not None:
            from scorpion.adk.workers import worker_generate_video
            import asyncio as _asyncio

            result_id = _adk_tools._pending_results.add(
                f"{self._origin_channel}:{self._origin_chat_id}",
                "video", prompt,
                {"duration": duration, "aspect": aspect, "resolution": resolution},
            )
            task = _asyncio.create_task(worker_generate_video(
                result_id, prompt, duration, aspect, resolution,
                api_key, _adk_tools._pending_results,
            ))
            _adk_tools._pending_results.register_task(result_id, task)
            logger.info(
                "[VideoGen] Spawned background worker {} for prompt={!r}",
                result_id, prompt[:60],
            )
            return (
                f"🎬 Video generation started in the background (id: {result_id}). "
                f"This takes 1–5 minutes. I'll deliver it when it's ready."
            )

        # Blocking fallback (CLI / no bus)
        return await _adk_tools.generate_video(
            prompt=prompt,
            duration=duration,
            aspect=aspect,
            resolution=resolution,
            tool_context=None,
        )


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
            return "Error: GEMINI_API_KEY not configured"

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
            return f"Error: {e}"
