"""Comprehensive input validation for security hardening.

This module provides validators for paths, glob patterns, and regex to prevent:
- Path traversal attacks
- ReDoS (Regular Expression Denial of Service) vulnerabilities
- Null byte injection
- Shell metacharacter injection

All validators follow a defense-in-depth approach with multiple validation layers.
"""

import os
import re
from pathlib import Path
from typing import FrozenSet, Optional, Tuple
from loguru import logger


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Maximum depth for glob patterns (e.g., **/* counts as depth)
MAX_GLOB_DEPTH: int = 10

# Maximum length for regex patterns to prevent ReDoS
MAX_REGEX_LENGTH: int = 1000

# Maximum regex execution timeout simulation (complexity threshold)
MAX_REGEX_COMPLEXITY: int = 100

# Dangerous characters that should be blocked in paths
DANGEROUS_PATH_CHARS: FrozenSet[str] = frozenset({
    '\x00',  # Null byte - can truncate paths in C-based systems
    '\n',    # Newline - can inject commands
    '\r',    # Carriage return
    '|',     # Pipe - shell metacharacter
    ';',     # Semicolon - command separator
    '&',     # Ampersand - command chaining
    '$',     # Dollar - variable expansion
    '`',     # Backtick - command substitution
    '!',     # History expansion
    '<',     # Redirect
    '>',     # Redirect
})

# Shell metacharacters for general input validation
SHELL_METACHARACTERS: FrozenSet[str] = frozenset({
    ';', '|', '&', '$', '`', '(', ')', '{', '}',
    '[', ']', '<', '>', '\\', '!', '#', '\n', '\r',
    '\x00', '*', '?', '~', '"', "'",
})

# Regex patterns that indicate potential ReDoS vulnerability
REDOS_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # Nested quantifiers - classic ReDoS pattern
    (r'\([^)]*[\+\*]\)[^\)]*[\+\*]', 'nested quantifiers'),
    (r'[\+\*]\s*[\+\*]', 'consecutive quantifiers'),
    (r'\(\?:.*[\+\*].*\)[\+\*]', 'quantified group with quantifier'),

    # Overlapping alternatives
    (r'\([^|)]+\|[^|)]+\)[\+\*]', 'overlapping alternatives with quantifier'),

    # Character class with quantifier followed by similar class
    (r'\[[^\]]+\][\+\*][^[]*\[[^\]]+\][\+\*]', 'repeated character classes'),

    # Backreferences with quantifiers (exponential backtracking)
    (r'\\[1-9].*[\+\*]', 'backreference with quantifier'),

    # Evil regex patterns
    (r'\(a\+\)\+', 'exponential backtracking pattern (a+)+'),
    (r'\(a\|a\)\+', 'overlapping alternatives (a|a)+'),
    (r'\(a\|b\?\)\+', 'optional in repeated alternation'),
)


class ValidationError(Exception):
    """Exception raised when input validation fails."""
    pass


class PathValidationError(ValidationError):
    """Exception raised when path validation fails."""
    pass


class GlobValidationError(ValidationError):
    """Exception raised when glob pattern validation fails."""
    pass


class RegexValidationError(ValidationError):
    """Exception raised when regex validation fails."""
    pass


# =============================================================================
# PATH VALIDATION
# =============================================================================

def validate_path(
    path: str,
    base_dir: Optional[str] = None,
    allow_absolute: bool = False,
    allow_symlinks: bool = False,
) -> Tuple[bool, str, Optional[Path]]:
    """Validate a path for security concerns.

    Args:
        path: The path string to validate.
        base_dir: If provided, ensure path stays within this directory.
        allow_absolute: Whether to allow absolute paths.
        allow_symlinks: Whether to allow symlinks (default False for security).

    Returns:
        Tuple of (is_valid, error_message, resolved_path).
        If valid, error_message is empty and resolved_path is the normalized path.
    """
    if not path:
        return False, "Empty path provided", None

    # Check for null bytes (critical security issue)
    if '\x00' in path:
        logger.warning(f"SECURITY: Null byte detected in path: {repr(path)}")
        return False, "Null byte detected in path (potential injection attack)", None

    # Check for dangerous characters
    dangerous_found = [c for c in path if c in DANGEROUS_PATH_CHARS]
    if dangerous_found:
        logger.warning(f"SECURITY: Dangerous characters in path: {dangerous_found}")
        return False, f"Dangerous characters detected in path: {dangerous_found}", None

    # Check for path traversal patterns
    traversal_patterns = ['../', '..\\', '/../', '\\..\\', '%2e%2e', '%252e%252e']
    path_lower = path.lower()
    for pattern in traversal_patterns:
        if pattern in path_lower:
            logger.warning(f"SECURITY: Path traversal pattern detected: {pattern}")
            return False, f"Path traversal pattern detected: {pattern}", None

    # Additional check for encoded traversal
    if '%' in path:
        try:
            from urllib.parse import unquote
            decoded = unquote(unquote(path))  # Double decode for double encoding attacks
            if '..' in decoded:
                logger.warning("SECURITY: Encoded path traversal detected")
                return False, "Encoded path traversal detected", None
        except Exception:
            pass

    # Check absolute path restriction
    if not allow_absolute and os.path.isabs(path):
        return False, "Absolute paths are not allowed", None

    try:
        # Create Path object for further validation
        p = Path(path)

        # Check for symlink if not allowed
        if not allow_symlinks:
            try:
                # Check if any component is a symlink
                current = Path('.')
                for part in p.parts:
                    current = current / part
                    if current.is_symlink():
                        logger.warning(f"SECURITY: Symlink detected in path: {current}")
                        return False, f"Symlinks are not allowed: {current}", None
            except (OSError, ValueError):
                pass  # Path doesn't exist yet, which is fine

        # If base_dir is provided, verify the path stays within it
        if base_dir:
            base_path = Path(base_dir).resolve()
            try:
                # Resolve the full path (handles .. and symlinks)
                if p.is_absolute():
                    full_path = p.resolve()
                else:
                    full_path = (base_path / p).resolve()

                # Check if resolved path is within base directory
                try:
                    full_path.relative_to(base_path)
                except ValueError:
                    logger.warning(f"SECURITY: Path escapes base directory: {path} -> {full_path}")
                    return False, f"Path escapes allowed directory: {base_dir}", None

                return True, "", full_path
            except (OSError, ValueError) as e:
                return False, f"Invalid path: {str(e)}", None

        return True, "", p

    except Exception as e:
        logger.error(f"Path validation error: {e}")
        return False, f"Path validation error: {str(e)}", None


def sanitize_path(path: str) -> str:
    """Sanitize a path by removing dangerous components.

    Args:
        path: The path string to sanitize.

    Returns:
        Sanitized path string.

    Note:
        This is a best-effort sanitization. Use validate_path() for actual
        validation before using paths in operations.
    """
    if not path:
        return ""

    # Remove null bytes
    sanitized = path.replace('\x00', '')

    # Remove other dangerous characters
    for char in DANGEROUS_PATH_CHARS:
        sanitized = sanitized.replace(char, '')

    # Normalize path separators
    sanitized = sanitized.replace('\\', '/')

    # Remove double slashes
    while '//' in sanitized:
        sanitized = sanitized.replace('//', '/')

    # Remove leading/trailing whitespace
    sanitized = sanitized.strip()

    return sanitized


# =============================================================================
# GLOB PATTERN VALIDATION
# =============================================================================

def validate_glob_pattern(
    pattern: str,
    max_depth: int = MAX_GLOB_DEPTH,
    allow_recursive: bool = True,
) -> Tuple[bool, str]:
    """Validate a glob pattern for security and performance concerns.

    Args:
        pattern: The glob pattern to validate.
        max_depth: Maximum allowed directory depth.
        allow_recursive: Whether to allow ** recursive patterns.

    Returns:
        Tuple of (is_valid, error_message).
    """
    if not pattern:
        return False, "Empty glob pattern"

    # Check for null bytes
    if '\x00' in pattern:
        logger.warning(f"SECURITY: Null byte in glob pattern: {repr(pattern)}")
        return False, "Null byte detected in glob pattern"

    # Check for shell metacharacters (except glob-specific ones)
    dangerous_for_glob = SHELL_METACHARACTERS - {'*', '?', '[', ']'}
    dangerous_found = [c for c in pattern if c in dangerous_for_glob]
    if dangerous_found:
        logger.warning(f"SECURITY: Shell metacharacters in glob: {dangerous_found}")
        return False, f"Shell metacharacters not allowed in glob pattern: {dangerous_found}"

    # Check for recursive patterns
    if '**' in pattern:
        if not allow_recursive:
            return False, "Recursive glob patterns (**) are not allowed"

        # Count depth of ** patterns
        double_star_count = pattern.count('**')
        if double_star_count > 2:
            return False, f"Too many recursive patterns (** appears {double_star_count} times)"

    # Check depth by counting path separators
    depth = pattern.count('/') + pattern.count('\\')
    if depth > max_depth:
        return False, f"Glob pattern depth ({depth}) exceeds maximum ({max_depth})"

    # Check for path traversal in glob
    if '..' in pattern:
        logger.warning(f"SECURITY: Path traversal in glob pattern: {pattern}")
        return False, "Path traversal (..) not allowed in glob patterns"

    # Check for absolute paths in glob
    if pattern.startswith('/') or (len(pattern) > 1 and pattern[1] == ':'):
        return False, "Absolute paths not allowed in glob patterns"

    # Check for overly broad patterns that could match too much
    if pattern == '*' or pattern == '**':
        logger.warning(f"SECURITY: Overly broad glob pattern: {pattern}")
        return False, "Pattern too broad - please be more specific"

    # Check for excessive wildcards
    wildcard_count = pattern.count('*') + pattern.count('?')
    if wildcard_count > 10:
        return False, f"Too many wildcards in pattern ({wildcard_count})"

    return True, ""


def sanitize_glob_pattern(pattern: str) -> str:
    """Sanitize a glob pattern by removing dangerous components.

    Args:
        pattern: The glob pattern to sanitize.

    Returns:
        Sanitized glob pattern.
    """
    if not pattern:
        return ""

    # Remove null bytes
    sanitized = pattern.replace('\x00', '')

    # Remove shell metacharacters (except glob-specific ones)
    allowed_glob_chars = {'*', '?', '[', ']', '-', '.', '/', '_'}
    sanitized = ''.join(
        c for c in sanitized
        if c.isalnum() or c in allowed_glob_chars
    )

    # Remove path traversal
    while '..' in sanitized:
        sanitized = sanitized.replace('..', '')

    return sanitized.strip()


# =============================================================================
# REGEX VALIDATION (ReDoS Prevention)
# =============================================================================

def validate_regex(
    pattern: str,
    max_length: int = MAX_REGEX_LENGTH,
    check_redos: bool = True,
) -> Tuple[bool, str]:
    """Validate a regex pattern for ReDoS vulnerabilities.

    Args:
        pattern: The regex pattern to validate.
        max_length: Maximum allowed pattern length.
        check_redos: Whether to check for ReDoS patterns.

    Returns:
        Tuple of (is_valid, error_message).
    """
    if not pattern:
        return False, "Empty regex pattern"

    # Check for null bytes
    if '\x00' in pattern:
        logger.warning(f"SECURITY: Null byte in regex: {repr(pattern)}")
        return False, "Null byte detected in regex pattern"

    # Check length
    if len(pattern) > max_length:
        return False, f"Regex pattern too long ({len(pattern)} > {max_length})"

    # Try to compile the regex to check for syntax errors
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex syntax: {str(e)}"

    # Check for ReDoS patterns
    if check_redos:
        redos_result = check_redos_vulnerability(pattern)
        if not redos_result[0]:
            return redos_result

    return True, ""


def check_redos_vulnerability(pattern: str) -> Tuple[bool, str]:
    """Check if a regex pattern is vulnerable to ReDoS attacks.

    Args:
        pattern: The regex pattern to check.

    Returns:
        Tuple of (is_safe, vulnerability_description).
        If vulnerable, is_safe is False.
    """
    # Check for known vulnerable patterns
    for vuln_pattern, description in REDOS_PATTERNS:
        try:
            if re.search(vuln_pattern, pattern):
                logger.warning(f"SECURITY: ReDoS vulnerability detected: {description}")
                return False, f"ReDoS vulnerability detected: {description}"
        except re.error:
            continue

    # Check for excessive quantifiers
    quantifier_count = len(re.findall(r'[\+\*\?]', pattern))
    if quantifier_count > 10:
        return False, f"Too many quantifiers ({quantifier_count}) - potential ReDoS risk"

    # Check for nested groups with quantifiers
    group_depth = 0
    max_group_depth = 0
    has_quantifier_at_depth: dict[int, bool] = {}

    i = 0
    while i < len(pattern):
        if pattern[i] == '\\' and i + 1 < len(pattern):
            i += 2  # Skip escaped character
            continue
        if pattern[i] == '(':
            group_depth += 1
            max_group_depth = max(max_group_depth, group_depth)
        elif pattern[i] == ')':
            if i + 1 < len(pattern) and pattern[i + 1] in '+*':
                has_quantifier_at_depth[group_depth] = True
            group_depth = max(0, group_depth - 1)
        i += 1

    if max_group_depth > 5:
        return False, f"Group nesting too deep ({max_group_depth}) - potential ReDoS risk"

    # Check for multiple quantifiers at different depths (exponential complexity)
    if len(has_quantifier_at_depth) > 2:
        return False, "Multiple nested groups with quantifiers - high ReDoS risk"

    return True, ""


def safe_regex_match(
    pattern: str,
    text: str,
    timeout_chars: int = 10000,
) -> Optional[re.Match]:
    """Perform a regex match with safety limits.

    Args:
        pattern: The regex pattern.
        text: The text to match against.
        timeout_chars: Maximum text length to process.

    Returns:
        Match object if found, None otherwise.

    Raises:
        RegexValidationError: If the pattern is invalid or text too long.
    """
    # Validate pattern first
    is_valid, error = validate_regex(pattern)
    if not is_valid:
        raise RegexValidationError(error)

    # Limit text length to prevent DoS
    if len(text) > timeout_chars:
        raise RegexValidationError(
            f"Text too long for regex matching ({len(text)} > {timeout_chars})"
        )

    try:
        return re.search(pattern, text)
    except Exception as e:
        raise RegexValidationError(f"Regex execution error: {str(e)}")


# =============================================================================
# GENERAL INPUT VALIDATION
# =============================================================================

def check_null_bytes(value: str, field_name: str = "input") -> Tuple[bool, str]:
    """Check for null bytes in input.

    Args:
        value: The string to check.
        field_name: Name of the field for error messages.

    Returns:
        Tuple of (is_safe, error_message).
    """
    if '\x00' in value:
        logger.warning(f"SECURITY: Null byte injection attempt in {field_name}")
        return False, f"Null byte detected in {field_name} (potential injection attack)"
    return True, ""


def check_shell_metacharacters(
    value: str,
    field_name: str = "input",
    allowed_chars: Optional[FrozenSet[str]] = None,
) -> Tuple[bool, str]:
    """Check for shell metacharacters in input.

    Args:
        value: The string to check.
        field_name: Name of the field for error messages.
        allowed_chars: Optional set of allowed metacharacters.

    Returns:
        Tuple of (is_safe, error_message).
    """
    blocked = SHELL_METACHARACTERS
    if allowed_chars:
        blocked = blocked - allowed_chars

    found = [c for c in value if c in blocked]
    if found:
        logger.warning(f"SECURITY: Shell metacharacters in {field_name}: {found}")
        return False, f"Shell metacharacters not allowed in {field_name}: {found}"
    return True, ""


def validate_input(
    value: str,
    field_name: str = "input",
    max_length: int = 10000,
    allow_empty: bool = False,
    check_null: bool = True,
    check_shell: bool = True,
) -> Tuple[bool, str]:
    """General input validation combining multiple checks.

    Args:
        value: The input string to validate.
        field_name: Name of the field for error messages.
        max_length: Maximum allowed length.
        allow_empty: Whether to allow empty input.
        check_null: Whether to check for null bytes.
        check_shell: Whether to check for shell metacharacters.

    Returns:
        Tuple of (is_valid, error_message).
    """
    # Check empty
    if not value:
        if allow_empty:
            return True, ""
        return False, f"{field_name} cannot be empty"

    # Check length
    if len(value) > max_length:
        return False, f"{field_name} too long ({len(value)} > {max_length})"

    # Check null bytes
    if check_null:
        is_safe, error = check_null_bytes(value, field_name)
        if not is_safe:
            return False, error

    # Check shell metacharacters
    if check_shell:
        is_safe, error = check_shell_metacharacters(value, field_name)
        if not is_safe:
            return False, error

    return True, ""


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def is_safe_path(path: str, base_dir: Optional[str] = None) -> bool:
    """Quick check if a path is safe.

    Args:
        path: The path to check.
        base_dir: Optional base directory to confine path to.

    Returns:
        True if path is safe, False otherwise.
    """
    is_valid, _, _ = validate_path(path, base_dir=base_dir)
    return is_valid


def is_safe_glob(pattern: str) -> bool:
    """Quick check if a glob pattern is safe.

    Args:
        pattern: The glob pattern to check.

    Returns:
        True if pattern is safe, False otherwise.
    """
    is_valid, _ = validate_glob_pattern(pattern)
    return is_valid


def is_safe_regex(pattern: str) -> bool:
    """Quick check if a regex pattern is safe.

    Args:
        pattern: The regex pattern to check.

    Returns:
        True if pattern is safe, False otherwise.
    """
    is_valid, _ = validate_regex(pattern)
    return is_valid
