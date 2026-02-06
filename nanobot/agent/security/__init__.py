"""Security module for input validation and hardening.

This module provides:
- Path validation (traversal, null bytes, shell injection)
- Glob pattern validation (depth limits, wildcards)
- Regex validation (ReDoS prevention)
- General input sanitization
- Prompt injection defense
"""

from nanobot.agent.security.validators import (
    # Path validation
    validate_path,
    sanitize_path,
    is_safe_path,
    PathValidationError,
    # Glob validation
    validate_glob_pattern,
    sanitize_glob_pattern,
    is_safe_glob,
    GlobValidationError,
    # Regex validation
    validate_regex,
    check_redos_vulnerability,
    safe_regex_match,
    is_safe_regex,
    RegexValidationError,
    # General validation
    validate_input,
    check_null_bytes,
    check_shell_metacharacters,
    ValidationError,
    # Constants
    MAX_GLOB_DEPTH,
    MAX_REGEX_LENGTH,
    MAX_REGEX_COMPLEXITY,
    DANGEROUS_PATH_CHARS,
    SHELL_METACHARACTERS,
    REDOS_PATTERNS,
)

from nanobot.agent.security.prompt_guard import (
    detect_injection,
    sanitize_external_content,
    INJECTION_PATTERNS,
)

__all__ = [
    # Path validation
    "validate_path",
    "sanitize_path",
    "is_safe_path",
    "PathValidationError",
    # Glob validation
    "validate_glob_pattern",
    "sanitize_glob_pattern",
    "is_safe_glob",
    "GlobValidationError",
    # Regex validation
    "validate_regex",
    "check_redos_vulnerability",
    "safe_regex_match",
    "is_safe_regex",
    "RegexValidationError",
    # General validation
    "validate_input",
    "check_null_bytes",
    "check_shell_metacharacters",
    "ValidationError",
    # Constants
    "MAX_GLOB_DEPTH",
    "MAX_REGEX_LENGTH",
    "MAX_REGEX_COMPLEXITY",
    "DANGEROUS_PATH_CHARS",
    "SHELL_METACHARACTERS",
    "REDOS_PATTERNS",
    # Prompt injection
    "detect_injection",
    "sanitize_external_content",
    "INJECTION_PATTERNS",
]
