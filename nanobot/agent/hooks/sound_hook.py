"""Agent hook that plays a completion chime from ``~/.nanobot/resource/sound``.

Drop any ``.mp3`` / ``.wav`` / ``.ogg`` / ``.m4a`` / ``.flac`` / ``.aac`` / ``.opus``
into that folder and it'll be played (fire-and-forget) when each agent run
finishes. No audio files → no-op. Playback failure is logged at debug level
and never raised — the hook is decorative.
"""

from __future__ import annotations

import os

import asyncio
import math
import struct
import sys
import wave
from pathlib import Path

import dotenv
dotenv.load_dotenv()
from loguru import logger

from nanobot.agent.hook import AgentHook, AgentRunHookContext
from nanobot.utils.helpers import ensure_dir


_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus"}
_DEFAULT_DIR = Path("~/.nanobot/resource/sound")
_DEFAULT_CHIME = "default_chime.wav"
_SAMPLE_RATE = 44100
_POP_DURATION_S = 0.08
_POP_F_START = 880.0
_POP_F_END = 220.0
_POP_DECAY_TAU = 0.020


def _player_argv() -> list[str]:
    """Return the command prefix that hands a file path to the OS player."""
    if sys.platform == "darwin":
        return ["afplay"]
    if sys.platform.startswith("win"):
        # `start` is a cmd builtin; empty title argument stops `start` eating the path.
        return ["cmd", "/c", "start", ""]
    # Linux / WSL / others: xdg-open is the closest thing to a universal handler.
    return ["xdg-open"]


def _synthesize_chime(path: Path) -> None:
    # ponytail: short percussive pop — downward sweep + exponential decay.
    total_frames = int(_POP_DURATION_S * _SAMPLE_RATE)
    samples = []
    for n in range(total_frames):
        t = n / _SAMPLE_RATE
        # Linear pitch sweep A5 → A3; integrate phase so the sweep is monotonic.
        phase = 2.0 * math.pi * (
            _POP_F_START * t
            - (_POP_F_START - _POP_F_END) * t * t / (2 * _POP_DURATION_S)
        )
        env = math.exp(-t / _POP_DECAY_TAU)
        sample = math.sin(phase) * env * 0.9
        samples.append(int(max(-1.0, min(1.0, sample)) * 32767))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def _ensure_default_sound(sound_dir: Path) -> None:
    ensure_dir(sound_dir)
    # If the user has already curated this folder, leave it alone — never
    # synthesize a default chime alongside their picks.
    try:
        has_audio = any(
            p.is_file() and p.suffix.lower() in _AUDIO_EXTS
            for p in sound_dir.iterdir()
        )
    except OSError:
        has_audio = False
    if has_audio:
        return
    _synthesize_chime(sound_dir / _DEFAULT_CHIME)


class SoundCompletionHook(AgentHook):
    """Play a random audio file from ``sound_dir`` after each agent run.

    Picks the first audio file (sorted) for deterministic behavior. Override
    ``sound_dir`` in the constructor to point elsewhere.

    On first construction the directory is created (if missing) and a short
    default chime is synthesized via stdlib so the hook works out-of-the-box
    without any user setup. User-supplied audio files always win (lex-first).
    """

    def __init__(self, sound_dir: Path | None = None) -> None:
        super().__init__()
        self._sound_dir = (
            Path(sound_dir).expanduser() if sound_dir else _DEFAULT_DIR.expanduser()
        )
        try:
            _ensure_default_sound(self._sound_dir)
        except Exception as exc:  # noqa: BLE001 — bootstrap is decorative
            logger.debug("sound hook: bootstrap failed ({})", exc)

    def _pick(self) -> Path | None:
        try:
            entries = [
                p
                for p in self._sound_dir.iterdir()
                if p.is_file() and p.suffix.lower() in _AUDIO_EXTS
            ]
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return None
        return sorted(entries)[0] if entries else None

    async def on_finally(self, context: AgentRunHookContext) -> None:
        path = self._pick()
        if path is None:
            return
        try:
            await asyncio.create_subprocess_exec(
                *_player_argv(),
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.debug("sound hook: player not found for {}", sys.platform)
        except OSError as exc:
            logger.debug("sound hook: failed to spawn player ({})", exc)


def create_sound_hook(sound_dir: Path | None = None) -> SoundCompletionHook | None:
    """Create a sound hook."""
    if not os.getenv("NANOBOT_SILENT"):
        return SoundCompletionHook(sound_dir)
    return None


_hook = create_sound_hook()
hooks: list[AgentHook] = [_hook] if _hook else []
