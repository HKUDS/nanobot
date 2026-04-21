"""Sensitive data detection, path blocking, and content redaction.

This module provides the shared security layer used by both the filesystem
tools (read_file, edit_file) and the shell tool (exec) to prevent leakage
of private keys, credentials, tokens, and other secrets.
"""

import os
import re
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# 1. Sensitive path detection
# ---------------------------------------------------------------------------

# Directories / files that must never be read or targeted by commands.
# Paths are checked after expanding ~ and resolving symlinks.
_SENSITIVE_PATH_PATTERNS: list[str] = [
    # SSH key material
    "/.ssh/",
    "/etc/ssh/ssh_host_",
    # System credential stores
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/security/opasswd",
    # GNOME / KDE keyrings
    "/.local/share/keyrings/",
    "/.kde/share/apps/kwallet/",
    # GPG private keyring
    "/.gnupg/private-keys-v1.d/",
    "/.gnupg/secring.gpg",
    # Cloud credential caches
    "/.aws/credentials",
    "/.aws/config",
    "/.azure/",
    "/.config/gcloud/credentials.db",
    "/.config/gcloud/application_default_credentials.json",
    # Docker config (may contain registry passwords)
    "/.docker/config.json",
    # Kubernetes
    "/.kube/config",
    # Password / secret files
    "/.netrc",
    "/.pgpass",
    "/.my.cnf",
]

# File name patterns that are sensitive regardless of directory
_SENSITIVE_FILENAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),            # .env, .env.local, .env.production
    re.compile(r"(^|/)credentials\.json$", re.IGNORECASE),
    re.compile(r"(^|/)service[-_]?account[-_]?key\.json$", re.IGNORECASE),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),       # SSH key files by name
    re.compile(r"(^|/).*\.pem$", re.IGNORECASE),
    re.compile(r"(^|/).*\.key$", re.IGNORECASE),                   # TLS private keys
]


def is_sensitive_path(path: str | Path) -> bool:
    """Return True if *path* points to a known sensitive location or file.

    The check is intentionally broad — it is better to block a false-positive
    than to leak a private key.
    """
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        resolved = str(path)

    # Absolute directory / prefix checks
    for pattern in _SENSITIVE_PATH_PATTERNS:
        if pattern in resolved:
            return True

    # Basename / filename checks
    for regex in _SENSITIVE_FILENAME_PATTERNS:
        if regex.search(resolved):
            return True

    return False


# ---------------------------------------------------------------------------
# 2. Content-level secret detection & redaction
# ---------------------------------------------------------------------------

# Regex patterns that match secret material inside file / command output.
_SECRET_CONTENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # PEM-encoded private keys (RSA, EC, DSA, OPENSSH, PKCS8, etc.)
    (re.compile(r"-----BEGIN\s+[\w\s]*PRIVATE\s+KEY-----", re.IGNORECASE), "private key"),
    # Certificates (optional — certificates are less secret, but the request asked for them)
    (re.compile(r"-----BEGIN\s+CERTIFICATE-----", re.IGNORECASE), "certificate"),
    # AWS-style keys
    (re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}", re.IGNORECASE), "AWS access key"),
    # Generic long hex/base64 tokens preceded by common labels
    (re.compile(
        r"""(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|auth[_-]?token|"""
        r"""password|passwd|bearer)\s*[:=]\s*['"]?[A-Za-z0-9_\-/.+]{20,}""",
        re.IGNORECASE,
    ), "credential/token"),
    # GitHub / GitLab / npm tokens
    (re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"), "GitHub token"),
    (re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"), "GitLab token"),
    (re.compile(r"npm_[A-Za-z0-9]{36,}"), "npm token"),
    # Slack tokens
    (re.compile(r"xox[bpras]-[A-Za-z0-9\-]{10,}"), "Slack token"),
    # Generic "PRIVATE KEY" blob (catches partial dumps)
    (re.compile(r"-----BEGIN\s+RSA", re.IGNORECASE), "RSA key material"),
    (re.compile(r"-----BEGIN\s+EC", re.IGNORECASE), "EC key material"),
    (re.compile(r"-----BEGIN\s+DSA", re.IGNORECASE), "DSA key material"),
    (re.compile(r"-----BEGIN\s+OPENSSH", re.IGNORECASE), "OpenSSH key material"),
]

_REDACTION_NOTICE = (
    "[REDACTED — sensitive content detected ({detail}). "
    "Displaying secrets is blocked by security policy.]"
)


def scan_content(text: str) -> str | None:
    """Scan *text* for secret material.

    Returns a human-readable description of the first match, or ``None``
    if the content appears clean.
    """
    for pattern, label in _SECRET_CONTENT_PATTERNS:
        if pattern.search(text):
            return label
    return None


def redact_if_sensitive(text: str) -> str:
    """Return *text* unchanged if clean, or a redacted message otherwise."""
    match = scan_content(text)
    if match:
        logger.warning("Redacted output containing: {}", match)
        return _REDACTION_NOTICE.format(detail=match)
    return text


# ---------------------------------------------------------------------------
# 3. Shell command pre-screening
# ---------------------------------------------------------------------------

# Commands whose primary purpose is to dump environment / secrets.
_BLOCKED_SHELL_COMMANDS: list[re.Pattern] = [
    # env-dumping commands (standalone or at start of pipe)
    re.compile(r"(?:^|\|)\s*(?:printenv|/usr/bin/printenv)\b"),
    re.compile(r"(?:^|\|)\s*\benv\b(?!\s+\S+\s*=)"),   # bare 'env' but not 'env VAR=val cmd'
    re.compile(r"(?:^|\|)\s*\bexport\s+-p\b"),
    re.compile(r"(?:^|\|)\s*\bset\s*$"),                 # bare 'set' dumps shell vars
    re.compile(r"(?:^|\|)\s*\bdeclare\s+-x\b"),
    # Direct reads of sensitive paths
    re.compile(r"\bcat\s+[~]?/?\.ssh/", re.IGNORECASE),
    re.compile(r"\bcat\s+/etc/shadow\b", re.IGNORECASE),
    re.compile(r"\bcat\s+.*\.env\b", re.IGNORECASE),
    re.compile(r"\bcat\s+.*\.pem\b", re.IGNORECASE),
    re.compile(r"\bcat\s+.*\.key\b", re.IGNORECASE),
    re.compile(r"\bcat\s+.*/credentials\.json\b", re.IGNORECASE),
    # Reading sensitive dirs with other tools
    re.compile(r"\b(?:less|more|head|tail|bat|nano|vim?|view)\s+[~]?/?\.ssh/", re.IGNORECASE),
    re.compile(r"\b(?:less|more|head|tail|bat|nano|vim?|view)\s+/etc/shadow\b", re.IGNORECASE),
    # Key scanning / dumping
    re.compile(r"\bssh-add\s+-[lL]\b"),
    re.compile(r"\bgpg\s+--export-secret", re.IGNORECASE),
    # Base64 encoding of key files (exfiltration attempt)
    re.compile(r"\bbase64\s+[~]?/?\.ssh/", re.IGNORECASE),
    re.compile(r"\bbase64\s+.*\.pem\b", re.IGNORECASE),
    re.compile(r"\bbase64\s+.*\.key\b", re.IGNORECASE),
    # xxd / od on key files
    re.compile(r"\b(?:xxd|od|hexdump)\s+[~]?/?\.ssh/", re.IGNORECASE),
]


def check_shell_command(command: str) -> str | None:
    """Screen a shell command for attempts to access sensitive data.

    Returns an error string if the command is blocked, or ``None`` if it
    passes the check.
    """
    for pattern in _BLOCKED_SHELL_COMMANDS:
        if pattern.search(command):
            logger.warning("Blocked sensitive shell command: {}", command)
            return (
                "Error: Command blocked by security policy — "
                "accessing sensitive data (keys, credentials, secrets) is not permitted."
            )
    return None
