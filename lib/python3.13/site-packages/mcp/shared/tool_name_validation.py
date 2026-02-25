"""Tool name validation utilities according to SEP-986.

Tool names SHOULD be between 1 and 128 characters in length (inclusive).
Tool names are case-sensitive.
Allowed characters: uppercase and lowercase ASCII letters (A-Z, a-z),
digits (0-9), underscore (_), dash (-), and dot (.).
Tool names SHOULD NOT contain spaces, commas, or other special characters.

See: https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-names
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Regular expression for valid tool names according to SEP-986 specification
TOOL_NAME_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# SEP reference URL for warning messages
SEP_986_URL = "https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-names"


@dataclass
class ToolNameValidationResult:
    """Result of tool name validation.

    Attributes:
        is_valid: Whether the tool name conforms to SEP-986 requirements.
        warnings: List of warning messages for non-conforming aspects.
    """

    is_valid: bool
    warnings: list[str] = field(default_factory=lambda: [])


def validate_tool_name(name: str) -> ToolNameValidationResult:
    """Validate a tool name according to the SEP-986 specification.

    Args:
        name: The tool name to validate.

    Returns:
        ToolNameValidationResult containing validation status and any warnings.
    """
    warnings: list[str] = []

    # Check for empty name
    if not name:
        return ToolNameValidationResult(
            is_valid=False,
            warnings=["Tool name cannot be empty"],
        )

    # Check length
    if len(name) > 128:
        return ToolNameValidationResult(
            is_valid=False,
            warnings=[f"Tool name exceeds maximum length of 128 characters (current: {len(name)})"],
        )

    # Check for problematic patterns (warnings, not validation failures)
    if " " in name:
        warnings.append("Tool name contains spaces, which may cause parsing issues")

    if "," in name:
        warnings.append("Tool name contains commas, which may cause parsing issues")

    # Check for potentially confusing leading/trailing characters
    if name.startswith("-") or name.endswith("-"):
        warnings.append("Tool name starts or ends with a dash, which may cause parsing issues in some contexts")

    if name.startswith(".") or name.endswith("."):
        warnings.append("Tool name starts or ends with a dot, which may cause parsing issues in some contexts")

    # Check for invalid characters
    if not TOOL_NAME_REGEX.match(name):
        # Find all invalid characters (unique, preserving order)
        invalid_chars: list[str] = []
        seen: set[str] = set()
        for char in name:
            if not re.match(r"[A-Za-z0-9._-]", char) and char not in seen:
                invalid_chars.append(char)
                seen.add(char)

        warnings.append(f"Tool name contains invalid characters: {', '.join(repr(c) for c in invalid_chars)}")
        warnings.append("Allowed characters are: A-Z, a-z, 0-9, underscore (_), dash (-), and dot (.)")

        return ToolNameValidationResult(is_valid=False, warnings=warnings)

    return ToolNameValidationResult(is_valid=True, warnings=warnings)


def issue_tool_name_warning(name: str, warnings: list[str]) -> None:
    """Log warnings for non-conforming tool names.

    Args:
        name: The tool name that triggered the warnings.
        warnings: List of warning messages to log.
    """
    if not warnings:
        return

    logger.warning(f'Tool name validation warning for "{name}":')
    for warning in warnings:
        logger.warning(f"  - {warning}")
    logger.warning("Tool registration will proceed, but this may cause compatibility issues.")
    logger.warning("Consider updating the tool name to conform to the MCP tool naming standard.")
    logger.warning(f"See SEP-986 ({SEP_986_URL}) for more details.")


def validate_and_warn_tool_name(name: str) -> bool:
    """Validate a tool name and issue warnings for non-conforming names.

    This is the primary entry point for tool name validation. It validates
    the name and logs any warnings via the logging module.

    Args:
        name: The tool name to validate.

    Returns:
        True if the name is valid, False otherwise.
    """
    result = validate_tool_name(name)
    issue_tool_name_warning(name, result.warnings)
    return result.is_valid
