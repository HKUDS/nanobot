"""Security module for Data Loss Prevention (DLP).

This module provides:
- Data Loss Prevention (DLP) capabilities
- Secret detection in content
- Secret redaction
- Egress safety checking
"""

from nanobot.agent.security.secrets import (
    scan_for_secrets,
    redact_secrets,
    check_egress_safe,
    scan_file_for_secrets,
    redact_for_logging,
    SECRET_PATTERNS,
    DLPConfig,
    get_dlp_config,
    configure_dlp,
)

__all__ = [
    # DLP/Secrets
    "scan_for_secrets",
    "redact_secrets",
    "check_egress_safe",
    "scan_file_for_secrets",
    "redact_for_logging",
    "SECRET_PATTERNS",
    "DLPConfig",
    "get_dlp_config",
    "configure_dlp",
]
