"""Text-to-speech provider using Microsoft Edge TTS."""

import asyncio
from pathlib import Path

import edge_tts
from loguru import logger


class EdgeTextToSpeechProvider:
    """
    Text-to-speech provider using Microsoft Edge TTS (edge-tts).

    Generates OGG/Opus audio files from text using Edge's neural voices,
    applying a 1.5x speed-up via ffmpeg for a snappier listening pace.
    """

    # Default voice - high quality English neural voice
    DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"

    def __init__(self, voice: str = DEFAULT_VOICE, rate: float = 1.0):
        """
        Parameters
        ----------
        voice:
            Edge TTS voice name (e.g. ``"en-US-AndrewMultilingualNeural"``).
            Run ``edge-tts --list-voices`` to see all options.
        rate:
            Speech rate adjustment (e.g. ``1.5`` for 1.5×, ``1.0`` for normal).
        """
        self.voice = voice
        self.rate = rate

    async def synthesize(self, text: str, output_path: str | Path) -> Path | None:
        """
        Convert *text* to speech and save the result as an OGG/Opus file.

        Parameters
        ----------
        text:
            The text to synthesise.
        output_path:
            Destination path for the OGG file (e.g. ``/tmp/reply.ogg``).

        Returns
        -------
        Path
            Path to the generated OGG file, or ``None`` on failure.
        """
        output_path = Path(output_path)
        mp3_path = output_path.with_suffix(".mp3")
        
        # Ensure the output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Synthesise to MP3 via Edge TTS

            # Convert float rate (e.g. 1.0, 1.5) to edge-tts expected format (e.g. "+0%", "+50%")
            # Clamp to valid range [0.25, 5.0]; otherwise, use "+0%"
            rate_str = "+0%"
            try:
                if 0.25 <= float(self.rate) <= 5.0:
                    percent = int(round((float(self.rate) - 1.0) * 100))
                    rate_str = f"{'+' if percent >= 0 else ''}{percent}%"
            except Exception:
                pass
            
            communicate = edge_tts.Communicate(text, self.voice, rate=rate_str)
            await communicate.save(str(mp3_path))

            # 2. Convert MP3 → OGG/Opus via ffmpeg
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(mp3_path),
                "-c:a", "libopus", "-b:a", "32k",
                "-vbr", "on", "-compression_level", "10",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"ffmpeg conversion failed: {stderr.decode()}")
                return None

            logger.debug(f"TTS audio saved to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            return None

        finally:
            if mp3_path.exists():
                try:
                    mp3_path.unlink()
                except Exception:
                    pass
