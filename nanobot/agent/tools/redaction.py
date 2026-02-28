"""Redaction guard - protects sensitive information from being exposed."""

import re
from pathlib import Path
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
    # OpenAI API keys (specific format)
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"), "sk-***"),
    # GitHub PATs
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "gh***"),
    # Slack tokens
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "xox***"),
    # Bearer tokens ( tightened - require minimum 20 chars)
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


def is_sensitive_path(path: Path) -> bool:
    """
    Check if a file path is sensitive and should be blocked.

    The path should already be normalized (using Path.resolve()) before calling
    this function, matching the same logic as _resolve_path() in filesystem.py.

    Args:
        path: Path object to check (should be already normalized/resolved)

    Returns:
        True if the path matches any sensitive pattern
    """
    if not path:
        return False

    # Get filename and extensions for matching
    name = path.name.lower()
    suffix = path.suffix.lower()
    suffixes = path.suffixes  # All suffixes (e.g., ['.pem', '.bak'])

    # Exact filename matches
    sensitive_filenames = {
        '.env', '.env.local', '.env.production', '.env.development',
        'auth.json', 'oauth.json',
        '.secrets',
        'identity',  # Old SSH private key format (deprecated but still sensitive)
    }

    # Filename prefix matches (e.g., '.env.development', 'secrets.json', 'credentials.yaml')
    sensitive_prefixes = ('.env.', 'secrets.', 'credentials.')

    # Extension matches (certificate/key files)
    # Check if ANY suffix in the chain is sensitive (e.g., .pem.bak contains .pem)
    sensitive_extensions = {
        '.pem', '.p12', '.pfx', '.jks', '.key',
    }

    # SSH private/public keys: id_<algorithm> or id_<algorithm>.pub
    # Pattern matches: id_rsa, id_rsa.pub, id_ed25519, id_ed25519.pub, etc.
    # Also matches security key variants: id_ecdsa-sk, id_ecdsa-sk.pub
    # Uses flexible pattern to catch current and future SSH key types
    import re
    ssh_key_pattern = re.compile(r'^id_[a-z0-9-]+(\.pub)?$', re.IGNORECASE)

    # Check exact filename match
    if name in sensitive_filenames:
        return True

    # Check SSH key files (using regex to match any algorithm)
    if ssh_key_pattern.match(name):
        return True

    # Check filename prefix
    if name.startswith(sensitive_prefixes):
        return True

    # Check if ANY suffix in the chain is sensitive
    # This catches: file.pem.bak, file.key.old, cert.p12.tmp, etc.
    # Backup files with sensitive extensions should still be blocked
    if any(s.lower() in sensitive_extensions for s in suffixes):
        return True

    return False


def redact_text(text: str) -> str:
    """
    Redact sensitive information from text.

    This function is idempotent - running it multiple times produces the same result.

    Args:
        text: The text to redact

    Returns:
        The redacted text
    """
    if not text or not isinstance(text, str):
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


def redact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Redact sensitive information from a list of messages.

    Args:
        messages: List of message dicts with 'content' field

    Returns:
        Messages with sensitive data redacted
    """
    redacted = []
    for msg in messages:
        content = msg.get("content")
        if content:
            redacted_content = redact_content(content)
            redacted.append({**msg, "content": redacted_content})
        else:
            redacted.append(msg)
    return redacted
