"""Tests for the audio-format normalization helper used by transcription providers.

The helper is best-effort: ffmpeg may be missing in the test environment, so we
exercise three branches:
  1. ``.wav`` input is passed through untouched.
  2. ffmpeg-missing branch returns the original path with no tempfile.
  3. ffmpeg-success branch returns a tempfile path and a cleanup pointer.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.providers.transcription import _ensure_whisper_compatible_audio


def test_wav_input_passes_through(tmp_path: Path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    upload, cleanup = _ensure_whisper_compatible_audio(wav)

    assert upload == wav
    assert cleanup is None


def test_missing_ffmpeg_returns_original(tmp_path: Path) -> None:
    ogg = tmp_path / "voice.ogg"
    ogg.write_bytes(b"OggS\x00")

    with patch("nanobot.providers.transcription.shutil.which", return_value=None):
        upload, cleanup = _ensure_whisper_compatible_audio(ogg)

    assert upload == ogg
    assert cleanup is None


def test_ffmpeg_failure_returns_original(tmp_path: Path) -> None:
    import subprocess

    ogg = tmp_path / "voice.ogg"
    ogg.write_bytes(b"OggS\x00")

    fake_error = subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"boom")
    with patch("nanobot.providers.transcription.shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("nanobot.providers.transcription.subprocess.run", side_effect=fake_error):
        upload, cleanup = _ensure_whisper_compatible_audio(ogg)

    assert upload == ogg
    assert cleanup is None


@pytest.mark.skipif(
    not __import__("shutil").which("ffmpeg"),
    reason="ffmpeg not installed in test environment",
)
def test_ffmpeg_real_conversion(tmp_path: Path) -> None:
    """Round-trip test that runs only when a real ffmpeg is on PATH."""
    import subprocess

    src = tmp_path / "tone.opus"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "libopus",
            str(src),
        ],
        check=True, capture_output=True,
    )

    upload, cleanup = _ensure_whisper_compatible_audio(src)
    try:
        assert cleanup is not None
        assert upload.suffix == ".wav"
        assert upload.stat().st_size > 0
    finally:
        if cleanup:
            Path(cleanup).unlink(missing_ok=True)
