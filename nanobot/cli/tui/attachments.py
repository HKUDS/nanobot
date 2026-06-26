"""Extract local file attachments (images, audio) from interactive TUI input.

Terminal users can't paste binary blobs, but dragging a file into most
terminals inserts its (often quoted or backslash-escaped) path. This module
pulls existing local paths out of the typed line so the TUI can forward images
as :attr:`InboundMessage.media` and transcribe audio before sending — giving
the CLI the multimodal input the WebUI offers. Detection is deliberately
conservative: a token must both have a known extension *and* resolve to an
existing file, so ordinary words are never mistaken for attachments.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tiff"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".webm"}


def _is_file_with_suffix(token: str, suffixes: set[str]) -> bool:
    path = Path(token).expanduser()
    return path.suffix.lower() in suffixes and path.is_file()


def _extract(text: str, suffixes: set[str]) -> tuple[str, list[str]]:
    """Split *text* into ``(remaining_text, matched_paths)`` for *suffixes*.

    Returns the input unchanged with an empty list when nothing matches, so
    normal messages keep their exact formatting. When attachments are detected
    the remaining text is rebuilt from the non-path tokens.
    """
    stripped = text.strip()
    if not stripped:
        return text, []
    try:
        tokens = shlex.split(stripped, posix=os.name != "nt")
    except ValueError:
        # Unbalanced quotes (e.g. an apostrophe) — treat as plain text.
        return text, []

    matched: list[str] = []
    kept: list[str] = []
    for token in tokens:
        token = token.strip("\"'")
        if _is_file_with_suffix(token, suffixes):
            matched.append(str(Path(token).expanduser().resolve()))
        else:
            kept.append(token)

    if not matched:
        return text, []
    return " ".join(kept), matched


def extract_media(text: str) -> tuple[str, list[str]]:
    """Pull existing local image paths out of *text*."""
    return _extract(text, _IMAGE_SUFFIXES)


def extract_audio(text: str) -> tuple[str, list[str]]:
    """Pull existing local audio paths out of *text* (for transcription)."""
    return _extract(text, _AUDIO_SUFFIXES)


def extract_attachments(text: str) -> tuple[str, list[str], list[str]]:
    """Pull image and audio paths out of *text*."""
    text, media = extract_media(text)
    text, audio = extract_audio(text)
    return text, media, audio
