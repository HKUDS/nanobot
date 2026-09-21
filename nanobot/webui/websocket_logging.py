"""Logging helpers for the WebUI WebSocket server surface."""

from __future__ import annotations

import logging

from websockets.exceptions import ConnectionClosed, InvalidMessage

OPENING_HANDSHAKE_FAILED_MESSAGE = "opening handshake failed"

# Exceptions that mean the browser hung up mid-handshake (e.g. a restart races an
# open tab) rather than a server fault.
_DISCONNECT_TYPES: tuple[type[BaseException], ...] = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
    ConnectionClosed,
    EOFError,
)

# InvalidMessage is raised when the peer never sends a valid WebSocket/HTTP-GET
# opening handshake: HEAD probes ("unsupported HTTP method; expected GET"),
# port scanners, uptime monitors, and TLS-to-plain-port attempts. On a public
# endpoint (e.g. a Render *.onrender.com service) this is constant background
# noise from the internet, not an operational error.
_MALFORMED_HANDSHAKE_TYPES: tuple[type[BaseException], ...] = (InvalidMessage,)

_SUPPRESSED_TYPES: tuple[type[BaseException], ...] = (
    _DISCONNECT_TYPES + _MALFORMED_HANDSHAKE_TYPES
)


def _exception_chain_has(exc: BaseException | None, types: tuple[type[BaseException], ...]) -> bool:
    seen: set[int] = set()
    while exc is not None:
        ident = id(exc)
        if ident in seen:
            return False
        seen.add(ident)
        if isinstance(exc, types):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class WebSocketHandshakeNoiseFilter(logging.Filter):
    """Suppress opening-handshake failures that are peer noise, not server faults.

    Covers browsers that disconnect during a restart and non-WebSocket requests
    (HEAD probes, port scanners, monitors) that hit the public port. Genuine
    server-side handshake errors are left to log.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != OPENING_HANDSHAKE_FAILED_MESSAGE:
            return True
        exc_info = record.exc_info
        exc = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) >= 2 else None
        return not _exception_chain_has(exc, _SUPPRESSED_TYPES)


def websockets_server_logger() -> logging.Logger:
    ws_logger = logging.getLogger("websockets.server")
    if not any(isinstance(f, WebSocketHandshakeNoiseFilter) for f in ws_logger.filters):
        ws_logger.addFilter(WebSocketHandshakeNoiseFilter())
    return ws_logger
