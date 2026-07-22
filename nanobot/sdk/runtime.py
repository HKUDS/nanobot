"""Runtime helpers for SDK calls."""

from __future__ import annotations

from typing import Any


def ensure_single_model_selector(
    *,
    model: str | None,
    model_preset: str | None,
) -> None:
    if model is not None and model_preset is not None:
        raise ValueError("model and model_preset are mutually exclusive")


def build_process_direct_kwargs(
    *,
    session_key: str,
    channel: str,
    chat_id: str,
    sender_id: str,
    media: list[str] | None,
    ephemeral: bool,
    on_stream: Any | None = None,
    on_stream_end: Any | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"session_key": session_key}
    if channel != "cli":
        kwargs["channel"] = channel
    if chat_id != "direct":
        kwargs["chat_id"] = chat_id
    if sender_id != "user":
        kwargs["sender_id"] = sender_id
    if media is not None:
        kwargs["media"] = media
    if ephemeral:
        kwargs["ephemeral"] = True
        kwargs["_run_extra_hooks_for_ephemeral"] = True
    if on_stream is not None:
        kwargs["on_stream"] = on_stream
    if on_stream_end is not None:
        kwargs["on_stream_end"] = on_stream_end
    return kwargs
