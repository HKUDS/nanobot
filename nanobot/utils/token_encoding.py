"""Offline fallback tokenizer for providers without a local token counter."""

import base64
import gzip
import hashlib
from functools import lru_cache
from importlib.resources import files
from threading import Lock

import tiktoken
from loguru import logger

_ENCODING_LOCK = Lock()
_VOCABULARY_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
# cl100k_base from tiktoken 0.12.0; see THIRD_PARTY_NOTICES.md.
_PATTERN = (
    r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+"
    r"| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"
)


@lru_cache(maxsize=1)
def _load_encoding() -> tiktoken.Encoding | None:
    """Cache success or failure so a broken install is not retried per message."""
    try:
        compressed = files("nanobot.utils").joinpath("cl100k_base.tiktoken.gz").read_bytes()
        vocabulary = gzip.decompress(compressed)
        if hashlib.sha256(vocabulary).hexdigest() != _VOCABULARY_SHA256:
            raise ValueError("bundled cl100k_base vocabulary checksum mismatch")
        ranks: dict[bytes, int] = {}
        for line in vocabulary.splitlines():
            token, rank = line.split()
            ranks[base64.b64decode(token, validate=True)] = int(rank)
        return tiktoken.Encoding(
            name="nanobot_cl100k_base",
            pat_str=_PATTERN,
            mergeable_ranks=ranks,
            # Prompt text may mention control tokens; count them as ordinary text.
            special_tokens={},
        )
    except Exception as exc:
        logger.warning(
            "Bundled token encoding unavailable ({}); using UTF-8 byte estimates "
            "until restart. Repair the nanobot installation to restore token estimation.",
            exc,
        )
        return None


def get_token_encoding() -> tiktoken.Encoding | None:
    """Load the bundled vocabulary once, without tiktoken's network-backed registry."""
    # lru_cache alone permits duplicate initialization on concurrent cache misses.
    with _ENCODING_LOCK:
        return _load_encoding()
