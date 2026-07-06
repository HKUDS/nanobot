"""Tests for WebUI websocket logging helpers."""

from __future__ import annotations

import logging

from nanobot.webui.websocket_logging import (
    OPENING_HANDSHAKE_FAILED_MESSAGE,
    WebSocketHandshakeNoiseFilter,
)


def _log_record(message: str, exc: BaseException) -> logging.LogRecord:
    return logging.LogRecord(
        name="websockets.server",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def test_websocket_handshake_noise_filter_suppresses_disconnects() -> None:
    filter_ = WebSocketHandshakeNoiseFilter()
    wrapped = RuntimeError("wrapped")
    wrapped.__cause__ = BrokenPipeError(32, "Broken pipe")
    empty_handshake = RuntimeError("wrapped")
    empty_handshake.__cause__ = EOFError("connection closed while reading HTTP request line")

    assert not filter_.filter(_log_record(OPENING_HANDSHAKE_FAILED_MESSAGE, BrokenPipeError()))
    assert not filter_.filter(_log_record(OPENING_HANDSHAKE_FAILED_MESSAGE, wrapped))
    assert not filter_.filter(_log_record(OPENING_HANDSHAKE_FAILED_MESSAGE, empty_handshake))


def test_websocket_handshake_noise_filter_keeps_real_errors() -> None:
    filter_ = WebSocketHandshakeNoiseFilter()

    assert filter_.filter(_log_record(OPENING_HANDSHAKE_FAILED_MESSAGE, RuntimeError("boom")))
    assert filter_.filter(_log_record("connection handler failed", BrokenPipeError()))
