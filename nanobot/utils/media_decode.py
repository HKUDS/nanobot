"""Shared helpers for decoding ``data:...;base64,...`` URLs to disk.

Historically lived in ``nanobot.api.server``; now shared by the WebSocket
channel so the ``api`` + ``websocket`` ingress paths apply the same parsing,
size guard, and filesystem layout.
"""

from __future__ import annotations

import asyncio
import base64
import io
import mimetypes
import os
import re
import tempfile
import uuid
from pathlib import Path

from nanobot.utils.helpers import safe_filename

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
MAX_FILE_SIZE = DEFAULT_MAX_BYTES

_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)


class FileSizeExceeded(Exception):
    """Raised when a decoded payload exceeds the caller's size limit."""


def save_base64_data_url(
    data_url: str,
    media_dir: Path,
    *,
    max_bytes: int | None = None,
) -> str | None:
    """Decode a ``data:<mime>;base64,<payload>`` URL and persist it.

    Returns the absolute path on success, ``None`` when the URL shape or the
    base64 payload itself is malformed. Raises :class:`FileSizeExceeded`
    when the decoded payload is larger than ``max_bytes`` (default 10 MB).
    """
    m = _DATA_URL_RE.match(data_url)
    if not m:
        return None
    mime_type, b64_payload = m.group(1), m.group(2)
    try:
        raw = base64.b64decode(b64_payload)
    except Exception:
        return None
    limit = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    if len(raw) > limit:
        raise FileSizeExceeded(f"File exceeds {limit // (1024 * 1024)}MB limit")

    # Special handling for audio/webm to use .webm extension instead of .weba
    if mime_type == "audio/webm":
        ext = ".webm"
    else:
        ext = mimetypes.guess_extension(mime_type) or ".bin"

    filename = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = media_dir / safe_filename(filename)
    dest.write_bytes(raw)
    return str(dest)


async def webm_to_wav_async(
    audio_bytes: bytes = None, input_file: Path = None, output_file: Path = None
) -> io.BytesIO | Path | None:
    """
    Convert non-WAV audio to WAV format using ffmpeg (async version).

    Args:
        audio_bytes: Raw audio data bytes (optional if input_file is provided)
        input_file: Path to input audio file (optional if audio_bytes is provided)
        output_file: Path to output WAV file (optional, returns BytesIO if not provided)

    Returns:
        BytesIO object with WAV data, or Path if output_file is specified, or None if conversion fails

    Note:
        Either audio_bytes or input_file must be provided, but not both.
    """
    # Validate input parameters
    if audio_bytes is None and input_file is None:
        raise ValueError("Either audio_bytes or input_file must be provided")
    if audio_bytes is not None and input_file is not None:
        raise ValueError("Cannot provide both audio_bytes and input_file")

    in_path, out_path = None, None
    try:
        # Prepare input file
        if input_file is not None:
            # Use the provided input file directly
            in_path = str(input_file)
        else:
            # Create temporary input file from audio_bytes
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
                tmp_in.write(audio_bytes)
                in_path = tmp_in.name

        # Create temporary output file for WAV
        if output_file:
            out_path = str(output_file)
        else:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                out_path = tmp_out.name

        # Use asyncio subprocess to avoid blocking the event loop
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i",
            in_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            "-y",
            out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await process.communicate()

        if process.returncode != 0:
            return None

        if output_file:
            return output_file
        # Read converted WAV file
        with open(out_path, "rb") as f:
            wav_io = io.BytesIO(f.read())
        return wav_io
    except FileNotFoundError:
        return None
    except Exception:
        return None
    finally:
        # Only unlink the input if it was a temporary file we created from audio_bytes
        if audio_bytes is not None and in_path and os.path.exists(in_path):
            os.unlink(in_path)
        if not output_file and out_path and os.path.exists(out_path):
            os.unlink(out_path)
