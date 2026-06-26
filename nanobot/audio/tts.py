"""Text-to-speech (TTS) tool for voice output."""

from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import NumberSchema, StringSchema, tool_parameters_schema
from nanobot.config.paths import get_media_dir

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"


def _find_tts_command() -> list[str] | None:
    """Return a TTS command that writes audio to a file, or None."""
    # Prefer edge-tts for cross-platform quality.
    edge_tts = shutil.which("edge-tts")
    if edge_tts:
        return [edge_tts, "--voice", "en-US-AriaNeural", "--text", "{text}", "--write-media", "{out}"]
    edge_playback = shutil.which("edge-playback")
    if edge_playback:
        return None  # edge-playback doesn't write files
    # macOS system TTS.
    if _IS_MACOS:
        say = shutil.which("say")
        if say:
            return [say, "-o", "{out}", "--data-format=mp4f", "{text}"]
    # Linux espeak-ng.
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        return [espeak, "-w", "{out}", "{text}"]
    # Windows SAPI via PowerShell.
    if _IS_WINDOWS:
        ps = shutil.which("powershell")
        if ps:
            return [
                ps, "-NoProfile", "-Command",
                'Add-Type -AssemblyName System.Speech; '
                '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                '$s.SetOutputToWaveFile(\"{out}\"); '
                '$s.Speak(\"{text}\"); '
                '$s.Dispose()',
            ]
    return None


@tool_parameters(
    tool_parameters_schema(
        text=StringSchema("The text to convert to speech"),
        voice=StringSchema(
            "Optional voice name. With edge-tts, use --list-voices to see options. "
            "Default: en-US-AriaNeural (edge-tts) or system default."
        ),
        speed=NumberSchema(
            description="Speech speed multiplier (0.5 to 2.0, default 1.0).",
            minimum=0.5,
            maximum=2.0,
        ),
        required=["text"],
    )
)
class TTSTool(Tool):
    """Convert text to speech and return an audio file path."""

    name = "tts"
    _scopes = {"core"}

    @property
    def description(self) -> str:
        return (
            "Convert text to speech and save as an MP3/WAV audio file. "
            "Use this when the user asks you to speak or read something aloud. "
            "Returns the file path for delivery via voice-capable channels."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        **kwargs: Any,
    ) -> str:
        if not text.strip():
            return "Error: text is empty"

        cmd_template = _find_tts_command()
        if not cmd_template:
            return (
                "Error: no TTS engine found. Install edge-tts: "
                "pip install edge-tts"
            )

        media_dir = get_media_dir("tts")
        media_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".mp3" if "edge-tts" in (cmd_template[0] if cmd_template else "") else ".wav"
        out_path = media_dir / f"tts-{uuid.uuid4().hex[:12]}{suffix}"

        # Build command with text sanitized for shell.
        safe_text = text.replace('"', '\\"').replace("\n", " ")
        cmd = [arg.format(text=safe_text, out=str(out_path)) for arg in cmd_template]

        if voice:
            idx = next((i for i, a in enumerate(cmd) if a == "--voice"), None)
            if idx is not None and idx + 1 < len(cmd):
                cmd[idx + 1] = voice

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=120,
            )
        except asyncio.TimeoutError:
            return "Error: TTS generation timed out"

        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            return f"Error: TTS failed (exit {process.returncode}): {err[:500]}"

        if not out_path.exists() or out_path.stat().st_size == 0:
            return "Error: TTS produced no output"

        logger.info("TTS generated: {} ({} bytes)", out_path, out_path.stat().st_size)
        return str(out_path)
