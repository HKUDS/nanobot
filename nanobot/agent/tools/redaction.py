"""Redaction guard - protects sensitive information from being exposed."""

import re
from typing import Any

# Redaction rules for sensitive data
# Order matters: more specific patterns should come first
REDACTION_RULES: list[tuple[str, re.Pattern[str], str]] = [
    # Private keys (most specific - must match full key)
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{1,10000}?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # SSH public keys (ssh-rsa, ssh-ed25519, ssh-dss, ecdsa-sha2-*)
    (
        "ssh_public_key",
        re.compile(r"\b(?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-\S+)\s+AAAA[A-Za-z0-9+/=]{40,}(?:\s+\S+)?"),
        "[REDACTED_SSH_PUBLIC_KEY]",
    ),
    # OpenAI API keys (specific format)
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"), "sk-***"),
    # GitHub PATs
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "gh***"),
    # Slack tokens
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "xox***"),
    # Bearer tokens (tightened - require minimum 20 chars)
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+\/-]{20,}=*\b", re.I), "Bearer ***"),
    # Password key-value patterns - JSON format (double quotes)
    (
        "password_kv_json",
        re.compile(r'"(\bpassword\b)"\s*:\s*"[^"]+"', re.I),
        r'"\1": "***"',
    ),
    # Password key-value patterns - non-JSON format
    (
        "password_kv",
        re.compile(r'(\bpassword\b)\s*[:=]\s*["\']?[^"\'\s,}]+["\']?', re.I),
        r'\1***',
    ),
    # API key key-value patterns - JSON format (double quotes, min 8 chars)
    (
        "api_key_kv_json",
        re.compile(r'"(\bapi[_-]?key\b)"\s*:\s*"[^"]{8,}"', re.I),
        r'"\1": "***"',
    ),
    # API key key-value patterns - non-JSON format (min 8 chars)
    (
        "api_key_kv",
        re.compile(r'(\bapi[_-]?key\b)\s*[:=]\s*["\']?[^"\'\s,}]{8,}["\']?', re.I),
        r'\1***',
    ),
    # Token key-value patterns - JSON format (double quotes)
    (
        "token_kv_json",
        re.compile(r'"(\b(?:token|access[_-]?token|refresh[_-]?token)\b)"\s*:\s*"[^"]+"', re.I),
        r'"\1": "***"',
    ),
    # Token key-value patterns - non-JSON format
    (
        "token_kv",
        re.compile(r'(\b(?:token|access[_-]?token|refresh[_-]?token)\b)\s*[:=]\s*["\']?[^"\'\s,}]+["\']?', re.I),
        r'\1***',
    ),
    # Secret key-value patterns - JSON format (double quotes)
    (
        "secret_kv_json",
        re.compile(r'"(\b(?:secret|client[_-]?secret|private[_-]?key)\b)"\s*:\s*"[^"]+"', re.I),
        r'"\1": "***"',
    ),
    # Secret key-value patterns - non-JSON format
    (
        "secret_kv",
        re.compile(r'(\b(?:secret|client[_-]?secret|private[_-]?key)\b)\s*[:=]\s*["\']?[^"\'\s,}]+["\']?', re.I),
        r'\1***',
    ),
]


def redact_text(text: str) -> str:
    """
    Redact sensitive information from text.

    This function is idempotent - running it multiple times produces the same result.

    Args:
        text: The text to redact

    Returns:
        The redacted text
    """
    if not text:
        return text

    result = text
    for _name, pattern, replacement in REDACTION_RULES:
        result = pattern.sub(replacement, result)
    return result


def redact_content(content: Any) -> Any:
    """
    Redact sensitive information from arbitrary content.

    Supports strings, lists (e.g., message content blocks), and other types.

    Args:
        content: The content to redact

    Returns:
        The redacted content (same type as input)
    """
    if isinstance(content, str):
        return redact_text(content)

    if isinstance(content, list):
        # Handle list of content blocks (e.g., [{"type": "text", "text": "..."}])
        redacted = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                redacted.append({**item, "text": redact_text(item["text"])})
            else:
                redacted.append(item)
        return redacted

    # For other types, return as-is
    return content



