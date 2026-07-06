"""Logging helpers for the WebUI WebSocket server surface."""

from __future__ import annotations

import logging

from websockets.exceptions import ConnectionClosed

OPENING_HANDSHAKE_FAILED_MESSAGE = "opening handshake failed"


def _exception_chain_has_disconnect(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    while exc is not None:
        ident = id(exc)
        if ident in seen:
            return False
        seen.add(ident)
        if isinstance(exc, (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
            ConnectionClosed,
            EOFError,
        )):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class WebSocketHandshakeNoiseFilter(logging.Filter):
    """Suppress restart-time handshakes where the browser already disconnected."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != OPENING_HANDSHAKE_FAILED_MESSAGE:
            return True
        exc_info = record.exc_info
        exc = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) >= 2 else None
        return not _exception_chain_has_disconnect(exc)


def websockets_server_logger() -> logging.Logger:
    ws_logger = logging.getLogger("websockets.server")
    if not any(isinstance(f, WebSocketHandshakeNoiseFilter) for f in ws_logger.filters):
        ws_logger.addFilter(WebSocketHandshakeNoiseFilter())
    return ws_logger
