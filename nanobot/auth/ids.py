"""ULID generation + validation for stable user identifiers.

A ULID is 128 bits encoded as 26 Crockford base32 characters:
  - first 10 chars  = 48-bit Unix epoch milliseconds (lexicographically sortable)
  - last  16 chars  = 80 bits of cryptographic randomness

Inline implementation avoids a third-party dep for ~30 lines of logic.
"""

from __future__ import annotations

import re
import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_ULID_LEN = 26


def _encode_int(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(*, now_ms: int | None = None) -> str:
    """Return a fresh 26-char Crockford-base32 ULID."""
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    if ts < 0 or ts >= (1 << 48):
        raise ValueError(f"timestamp out of ULID range: {ts}")
    rand_bytes = secrets.token_bytes(10)
    rand_int = int.from_bytes(rand_bytes, "big")
    return _encode_int(ts, 10) + _encode_int(rand_int, 16)


def is_ulid(value: str) -> bool:
    """Return True if value is a syntactically valid ULID string."""
    return isinstance(value, str) and len(value) == _ULID_LEN and bool(_ULID_RE.match(value))


def assert_ulid(value: str) -> str:
    """Return value if valid ULID; raise ValueError otherwise."""
    if not is_ulid(value):
        raise ValueError(f"invalid ULID: {value!r}")
    return value
