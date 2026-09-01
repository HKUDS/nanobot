"""Regression tests for WebSocket listener health probing portability."""

from __future__ import annotations

import errno
import socket
from typing import Any

import pytest

from nanobot.channels.websocket.runtime import WebSocketChannel


class _StubSocket:
    """Minimal socket stand-in: real sockets forbid attribute patching."""

    def __init__(self, *, fileno: int, error: OSError | None = None, value: int = 1):
        self._fileno = fileno
        self._error = error
        self._value = value

    def fileno(self) -> int:
        return self._fileno

    def getsockopt(self, *_args: Any, **_kwargs: Any) -> int:
        if self._error is not None:
            raise self._error
        return self._value


class _StubServer:
    """Minimal server stand-in for the production listener-health boundary."""

    def __init__(self, sock: _StubSocket, *, serving: bool = True):
        self._sock = sock
        self._serving = serving

    @property
    def sockets(self) -> tuple[_StubSocket, ...]:
        return (self._sock,)

    def is_serving(self) -> bool:
        return self._serving


@pytest.fixture
def listening_socket() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    yield sock
    sock.close()


def test_real_listening_socket_is_accepting(listening_socket: socket.socket) -> None:
    """A genuinely listening socket must never be reported as degraded.

    On macOS/BSD this exercises the ``ENOPROTOOPT`` fallback path; on Linux it
    exercises the native ``SO_ACCEPTCONN`` path. Both must agree.
    """
    assert WebSocketChannel._socket_is_accepting(listening_socket) is True


def test_closed_socket_is_not_accepting() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.close()

    assert WebSocketChannel._socket_is_accepting(sock) is False


@pytest.mark.parametrize(
    "unsupported_errno",
    [errno.ENOPROTOOPT, errno.EOPNOTSUPP],
)
def test_unsupported_sockopt_falls_back_to_fd_liveness(unsupported_errno: int) -> None:
    """macOS/BSD reject ``SO_ACCEPTCONN`` even on healthy listeners.

    Treating that rejection as "not serving" made the listener look permanently
    degraded, so the channel retried forever and never became ready.
    """
    sock = _StubSocket(fileno=3, error=OSError(unsupported_errno, "Protocol not available"))

    assert WebSocketChannel._socket_is_accepting(sock) is True


def test_listener_health_uses_unsupported_sockopt_fallback() -> None:
    """The fallback must be wired into the health check that controls readiness."""
    sock = _StubSocket(fileno=3, error=OSError(errno.ENOPROTOOPT, "Protocol not available"))
    server: Any = _StubServer(sock)

    assert WebSocketChannel._listener_is_serving(server) is True


def test_unexpected_oserror_propagates() -> None:
    sock = _StubSocket(fileno=3, error=OSError(errno.EBADF, "Bad file descriptor"))

    with pytest.raises(OSError) as excinfo:
        WebSocketChannel._socket_is_accepting(sock)

    assert excinfo.value.errno == errno.EBADF


def test_listener_health_rejects_invalid_socket_state() -> None:
    """``EINVAL`` can mean that a live socket isn't actually listening."""
    sock = _StubSocket(fileno=3, error=OSError(errno.EINVAL, "Invalid argument"))
    server: Any = _StubServer(sock)

    assert WebSocketChannel._listener_is_serving(server) is False


def test_unsupported_sockopt_still_rejects_dead_fd() -> None:
    """The portability fallback must not mask an already-closed listener."""
    sock = _StubSocket(fileno=-1, error=OSError(errno.ENOPROTOOPT, "Protocol not available"))

    assert WebSocketChannel._socket_is_accepting(sock) is False
