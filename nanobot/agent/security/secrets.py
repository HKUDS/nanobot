"""Secrets detection and DLP utilities."""
import re
from typing import Optional
from loguru import logger

# Patterns for detecting various types of secrets
SECRET_PATTERNS = {
    'aws_access_key': r'AKIA[0-9A-Z]{16}',
    'aws_secret_key': r'(?i)aws[_-]?secret[_-]?access[_-]?key["\s:=]+[A-Za-z0-9/+=]{40}',
    'github_pat': r'ghp_[A-Za-z0-9]{36}',
    'github_oauth': r'gho_[A-Za-z0-9]{36}',
    'openai_key': r'sk-[A-Za-z0-9]{48,}',
    'anthropic_key': r'sk-ant-[A-Za-z0-9-]{90,}',
    'private_key': r'-----BEGIN[^-]+PRIVATE KEY-----',
    'generic_api_key': r'(?i)(api[_-]?key|apikey)["\s:=]+[A-Za-z0-9_-]{20,}',
    'jwt_token': r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*',
    'slack_token': r'xox[baprs]-[0-9A-Za-z-]+',
    'telegram_token': r'[0-9]+:AA[A-Za-z0-9_-]{33}',
    'google_api_key': r'AIza[0-9A-Za-z_-]{35}',
    'stripe_key': r'(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{24,}',
    'password_in_url': r'(?i)(?:https?://)[^:]+:[^@]+@',
    'basic_auth_header': r'(?i)authorization:\s*basic\s+[A-Za-z0-9+/=]+',
    'bearer_token': r'(?i)bearer\s+[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
}

# Compiled regex patterns for performance
_COMPILED_PATTERNS: dict[str, re.Pattern] = {}


def _get_compiled_pattern(secret_type: str, pattern: str) -> re.Pattern:
    """Get or create a compiled regex pattern."""
    if secret_type not in _COMPILED_PATTERNS:
        _COMPILED_PATTERNS[secret_type] = re.compile(pattern)
    return _COMPILED_PATTERNS[secret_type]


def scan_for_secrets(content: str) -> list[tuple[str, str]]:
    """
    Scan content for potential secrets.

    Args:
        content: The text content to scan.

    Returns:
        List of tuples containing (secret_type, matched_pattern) for each found secret.
    """
    found = []
    for secret_type, pattern in SECRET_PATTERNS.items():
        compiled = _get_compiled_pattern(secret_type, pattern)
        if compiled.search(content):
            found.append((secret_type, pattern))
            logger.debug(f"DLP: Detected potential {secret_type}")
    return found


def redact_secrets(content: str, mask_char: str = "*") -> str:
    """
    Redact detected secrets from content.

    Args:
        content: The text content to redact.
        mask_char: Character to use for masking (unused, uses descriptive labels).

    Returns:
        Content with secrets replaced by redaction markers.
    """
    redacted = content
    for secret_type, pattern in SECRET_PATTERNS.items():
        compiled = _get_compiled_pattern(secret_type, pattern)
        redacted = compiled.sub(f'[REDACTED_{secret_type.upper()}]', redacted)
    return redacted


def check_egress_safe(content: str) -> tuple[bool, list[str]]:
    """
    Check if content is safe for egress (leaving the system).

    This function should be called before sending content to external
    services, APIs, or logging systems to prevent accidental secret leakage.

    Args:
        content: The content to check for secrets.

    Returns:
        Tuple of (is_safe, list_of_secret_types_found).
        is_safe is True if no secrets were detected.
    """
    secrets = scan_for_secrets(content)
    if secrets:
        secret_types = [s[0] for s in secrets]
        logger.warning(f"DLP: Blocked egress with {len(secrets)} potential secrets: {secret_types}")
        return False, secret_types
    return True, []


def scan_file_for_secrets(file_path: str) -> list[tuple[str, str, int]]:
    """
    Scan a file for secrets, returning line numbers.

    Args:
        file_path: Path to the file to scan.

    Returns:
        List of tuples containing (secret_type, matched_text, line_number).
    """
    from pathlib import Path

    found = []
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            for secret_type, pattern in SECRET_PATTERNS.items():
                compiled = _get_compiled_pattern(secret_type, pattern)
                match = compiled.search(line)
                if match:
                    # Don't include the actual secret, just indicate presence
                    found.append((secret_type, f"[MATCH_AT_POS_{match.start()}]", line_num))
                    logger.warning(f"DLP: Found {secret_type} in {file_path}:{line_num}")
    except Exception as e:
        logger.error(f"DLP: Error scanning file {file_path}: {e}")

    return found


def redact_for_logging(content: str, max_length: Optional[int] = 1000) -> str:
    """
    Prepare content for safe logging by redacting secrets and truncating.

    Args:
        content: The content to prepare for logging.
        max_length: Maximum length of the output (None for no limit).

    Returns:
        Safe-to-log version of the content.
    """
    redacted = redact_secrets(content)
    if max_length and len(redacted) > max_length:
        redacted = redacted[:max_length] + f"... [truncated, {len(content) - max_length} more chars]"
    return redacted


class DLPConfig:
    """Configuration for DLP behavior."""

    def __init__(
        self,
        enabled: bool = True,
        block_on_detection: bool = True,
        log_detections: bool = True,
        custom_patterns: Optional[dict[str, str]] = None,
    ):
        """
        Initialize DLP configuration.

        Args:
            enabled: Whether DLP checking is enabled.
            block_on_detection: Whether to block operations when secrets are detected.
            log_detections: Whether to log when secrets are detected.
            custom_patterns: Additional custom patterns to check.
        """
        self.enabled = enabled
        self.block_on_detection = block_on_detection
        self.log_detections = log_detections
        self.custom_patterns = custom_patterns or {}

    def get_all_patterns(self) -> dict[str, str]:
        """Get all patterns including custom ones."""
        patterns = SECRET_PATTERNS.copy()
        patterns.update(self.custom_patterns)
        return patterns


# Global DLP configuration instance
_dlp_config: Optional[DLPConfig] = None


def get_dlp_config() -> DLPConfig:
    """Get the global DLP configuration."""
    global _dlp_config
    if _dlp_config is None:
        _dlp_config = DLPConfig()
    return _dlp_config


def configure_dlp(config: DLPConfig) -> None:
    """Set the global DLP configuration."""
    global _dlp_config
    _dlp_config = config
    logger.info(f"DLP: Configuration updated - enabled={config.enabled}, block={config.block_on_detection}")
