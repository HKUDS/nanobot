"""Sans-I/O implementation of SOCKS4, SOCKS4A, and SOCKS5."""

from .exceptions import ProtocolError, SOCKSError
from .socks4 import (
    SOCKS4ARequest,
    SOCKS4Command,
    SOCKS4Connection,
    SOCKS4Reply,
    SOCKS4ReplyCode,
    SOCKS4Request,
)
from .socks5 import (
    SOCKS5AType,
    SOCKS5AuthMethod,
    SOCKS5AuthMethodsRequest,
    SOCKS5AuthReply,
    SOCKS5Command,
    SOCKS5CommandRequest,
    SOCKS5Connection,
    SOCKS5Reply,
    SOCKS5ReplyCode,
    SOCKS5UsernamePasswordRequest,
)

__version__ = "1.0.0"

__all__ = [
    "SOCKS4Request",
    "SOCKS4ARequest",
    "SOCKS4Reply",
    "SOCKS4Connection",
    "SOCKS4Command",
    "SOCKS4ReplyCode",
    "SOCKS5AType",
    "SOCKS5AuthMethodsRequest",
    "SOCKS5AuthReply",
    "SOCKS5AuthMethod",
    "SOCKS5Connection",
    "SOCKS5Command",
    "SOCKS5CommandRequest",
    "SOCKS5ReplyCode",
    "SOCKS5Reply",
    "SOCKS5UsernamePasswordRequest",
    "SOCKSError",
    "ProtocolError",
]
