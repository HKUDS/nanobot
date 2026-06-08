"""WebUI transcription envelope handling.

The WebSocket channel owns transport and subscription fan-out. This module owns
the WebUI-specific audio transcription action carried over that socket.
"""

from __future__ import annotations

from typing import Any

from nanobot.audio.transcription import (
    TranscriptionIngressError,
    resolve_transcription_config,
    transcribe_audio_data_url,
)
from nanobot.config.loader import load_config

_MAX_REQUEST_ID_LENGTH = 80


async def webui_transcription_event(envelope: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the WS event name and payload for one WebUI transcription request."""
    request_id = envelope.get("request_id")
    valid_request_id = (
        isinstance(request_id, str)
        and 0 < len(request_id) <= _MAX_REQUEST_ID_LENGTH
    )

    def error(detail: str, **extra: Any) -> tuple[str, dict[str, Any]]:
        payload: dict[str, Any] = {"detail": detail, **extra}
        if valid_request_id:
            payload["request_id"] = request_id
        return "transcription_error", payload

    if not valid_request_id:
        return error("invalid_request")

    try:
        text = await transcribe_audio_data_url(
            envelope.get("data_url"),
            resolve_transcription_config(load_config()),
            duration_ms=envelope.get("duration_ms"),
        )
    except TranscriptionIngressError as exc:
        return error(exc.detail, **exc.extra)
    return "transcription_result", {"request_id": request_id, "text": text}
