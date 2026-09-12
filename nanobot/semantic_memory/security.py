"""Conservative filtering for text entering semantic memory."""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_memory_text(text: str, *, max_chars: int = 16_000) -> str:
    """Normalize text and redact common credentials before persistence."""
    value = _CONTROL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED SECRET]", value)
    value = value.strip()
    if not value or value == "[REDACTED SECRET]":
        return ""
    return value[:max_chars]


def escape_runtime_excerpt(text: str) -> str:
    """Prevent recalled data from closing the runtime-context envelope."""
    return text.replace("[", "\\u005b").replace("]", "\\u005d")
