"""Security audit logging utilities.

This module provides comprehensive security audit logging for the Nanobot agent,
including:
- Log injection prevention through input sanitization
- Sensitive data redaction (API keys, passwords, credentials)
- Structured audit logging for tool execution, shell commands, and file operations

Security Features:
- Sanitizes newlines, carriage returns, escape sequences, and null bytes
- Redacts common credential patterns (OpenAI keys, AWS keys, passwords)
- Enforces length limits to prevent log flooding attacks
- Uses structured logging format for easy parsing and monitoring
"""

import json
import re
from typing import Any

from loguru import logger


# Characters that can be used for log injection attacks
LOG_INJECTION_CHARS: frozenset[str] = frozenset({
    '\n',    # Newline - can create fake log entries
    '\r',    # Carriage return - can overwrite log lines
    '\x1b',  # ANSI escape - can manipulate terminal output
    '\x00',  # Null byte - can truncate or corrupt logs
})


def sanitize_log_input(value: str, max_length: int = 500) -> str:
    """Sanitize input for safe logging.

    Removes or replaces characters that could be used for log injection attacks
    and enforces a maximum length to prevent log flooding.

    Args:
        value: The input value to sanitize
        max_length: Maximum allowed length (default 500)

    Returns:
        Sanitized string safe for logging

    Examples:
        >>> sanitize_log_input("normal text")
        'normal text'
        >>> sanitize_log_input("line1\\nline2")
        'line1 line2'
        >>> sanitize_log_input("a" * 600, max_length=10)
        'aaaaaaaaaa...'
    """
    # Convert to string and handle None
    if value is None:
        return ""

    sanitized = str(value)

    # Replace injection characters with spaces
    for char in LOG_INJECTION_CHARS:
        sanitized = sanitized.replace(char, ' ')

    # Additional sanitization: remove other control characters
    sanitized = ''.join(
        c if c.isprintable() or c == ' ' else ' '
        for c in sanitized
    )

    # Collapse multiple spaces
    sanitized = ' '.join(sanitized.split())

    # Truncate if too long
    if len(sanitized) > max_length:
        return sanitized[:max_length] + '...'

    return sanitized


def redact_for_logging(content: str) -> str:
    """Redact sensitive data before logging.

    Identifies and redacts common credential patterns to prevent
    accidental exposure of secrets in logs.

    Patterns redacted:
    - OpenAI API keys (sk-...)
    - AWS Access Key IDs (AKIA...)
    - Passwords in various formats
    - GitHub tokens (ghp_..., gho_..., etc.)
    - Generic API keys and secrets
    - Bearer tokens
    - Private keys

    Args:
        content: The content to redact

    Returns:
        Content with sensitive data redacted

    Examples:
        >>> redact_for_logging("key=sk-abc123xyz")
        'key=sk-[REDACTED]'
        >>> redact_for_logging("password=secret123")
        'password=[REDACTED]'
    """
    if not content:
        return content

    redacted = content

    # OpenAI API keys
    redacted = re.sub(
        r'sk-[A-Za-z0-9]{20,}',
        'sk-[REDACTED]',
        redacted
    )

    # AWS Access Key IDs
    redacted = re.sub(
        r'AKIA[0-9A-Z]{16}',
        'AKIA[REDACTED]',
        redacted
    )

    # AWS Secret Access Keys (40 character base64)
    redacted = re.sub(
        r'(?i)(aws.?secret.?(?:access.?)?key)\s*[:=]\s*[A-Za-z0-9+/]{40}',
        r'\1=[REDACTED]',
        redacted
    )

    # Password patterns (various formats)
    redacted = re.sub(
        r'(?i)(password|passwd|pwd|pass)\s*[:=]\s*\S+',
        r'\1=[REDACTED]',
        redacted
    )

    # Generic secret/token/key patterns
    redacted = re.sub(
        r'(?i)(secret|token|api.?key|private.?key|auth.?key|access.?token)\s*[:=]\s*\S+',
        r'\1=[REDACTED]',
        redacted
    )

    # GitHub tokens
    redacted = re.sub(
        r'(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}',
        r'\1_[REDACTED]',
        redacted
    )

    # Bearer tokens in authorization headers
    redacted = re.sub(
        r'(?i)(bearer)\s+[a-zA-Z0-9._-]+',
        r'\1 [REDACTED]',
        redacted
    )

    # Private key blocks
    redacted = re.sub(
        r'-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----',
        '-----BEGIN PRIVATE KEY-----[REDACTED]-----END PRIVATE KEY-----',
        redacted
    )

    return redacted


class SecurityAudit:
    """Security audit logging class for tracking sensitive operations.

    Provides structured logging methods for:
    - Tool execution tracking
    - Shell command auditing
    - File operation monitoring
    - Security event logging

    All methods automatically sanitize inputs and redact sensitive data
    before writing to logs.

    Usage:
        from nanobot.agent.security.audit import audit

        # Log tool execution
        audit.log_tool_exec("shell", {"command": "ls -la"}, "user1", "cli")

        # Log shell command
        audit.log_shell_cmd("git status", "/workspace")

        # Log file access
        audit.log_file_access("read", "/workspace/config.py")
    """

    @staticmethod
    def log_tool_exec(
        tool: str,
        args: dict[str, Any],
        user: str,
        channel: str,
        success: bool = True
    ) -> None:
        """Log tool execution with sanitized arguments.

        Args:
            tool: Name of the tool being executed
            args: Arguments passed to the tool
            user: User identifier
            channel: Source channel (cli, telegram, discord, etc.)
            success: Whether the execution was successful
        """
        # Sanitize and redact all arguments
        safe_args: dict[str, str] = {}
        for key, value in args.items():
            sanitized = sanitize_log_input(str(value), max_length=200)
            safe_args[key] = redact_for_logging(sanitized)

        status = "SUCCESS" if success else "FAILED"
        safe_tool = sanitize_log_input(tool, max_length=50)
        safe_user = sanitize_log_input(user, max_length=100)
        safe_channel = sanitize_log_input(channel, max_length=50)

        logger.info(
            f"AUDIT:TOOL:{status} "
            f"tool={safe_tool} "
            f"user={safe_user} "
            f"channel={safe_channel} "
            f"args={json.dumps(safe_args)}"
        )

    @staticmethod
    def log_shell_cmd(
        cmd: str,
        cwd: str,
        blocked: bool = False,
        reason: str | None = None,
        exit_code: int | None = None
    ) -> None:
        """Log shell command execution or blocking.

        Args:
            cmd: The shell command
            cwd: Working directory
            blocked: Whether the command was blocked
            reason: Reason for blocking (if blocked)
            exit_code: Exit code (if executed)
        """
        status = "BLOCKED" if blocked else "EXEC"
        safe_cmd = sanitize_log_input(cmd, max_length=300)
        safe_cmd = redact_for_logging(safe_cmd)
        safe_cwd = sanitize_log_input(cwd, max_length=200)

        log_msg = (
            f"AUDIT:SHELL_{status} "
            f"cmd={safe_cmd} "
            f"cwd={safe_cwd}"
        )

        if blocked and reason:
            safe_reason = sanitize_log_input(reason, max_length=200)
            log_msg += f" reason={safe_reason}"

        if exit_code is not None:
            log_msg += f" exit_code={exit_code}"

        # Use warning level for blocked commands
        if blocked:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    @staticmethod
    def log_file_access(
        op: str,
        path: str,
        blocked: bool = False,
        reason: str | None = None,
        bytes_accessed: int | None = None
    ) -> None:
        """Log file operation audit event.

        Args:
            op: Operation type (read, write, edit, list)
            path: File or directory path
            blocked: Whether the operation was blocked
            reason: Reason for blocking (if blocked)
            bytes_accessed: Number of bytes read/written (if applicable)
        """
        status = "BLOCKED" if blocked else "OK"
        safe_op = sanitize_log_input(op, max_length=20)
        safe_path = sanitize_log_input(str(path), max_length=300)
        safe_path = redact_for_logging(safe_path)

        log_msg = (
            f"AUDIT:FILE_{status} "
            f"op={safe_op} "
            f"path={safe_path}"
        )

        if blocked and reason:
            safe_reason = sanitize_log_input(reason, max_length=200)
            log_msg += f" reason={safe_reason}"

        if bytes_accessed is not None:
            log_msg += f" bytes={bytes_accessed}"

        # Use warning level for blocked operations
        if blocked:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    @staticmethod
    def log_security_event(
        event_type: str,
        description: str,
        severity: str = "INFO",
        context: dict[str, Any] | None = None
    ) -> None:
        """Log a general security event.

        Args:
            event_type: Type of security event (AUTH, ACCESS, VIOLATION, etc.)
            description: Human-readable description
            severity: Log level (INFO, WARNING, ERROR, CRITICAL)
            context: Additional context information
        """
        safe_event_type = sanitize_log_input(event_type, max_length=50)
        safe_description = sanitize_log_input(description, max_length=500)
        safe_description = redact_for_logging(safe_description)

        log_msg = f"AUDIT:SECURITY:{safe_event_type} {safe_description}"

        if context:
            safe_context: dict[str, str] = {}
            for key, value in context.items():
                sanitized = sanitize_log_input(str(value), max_length=100)
                safe_context[key] = redact_for_logging(sanitized)
            log_msg += f" context={json.dumps(safe_context)}"

        # Select log level
        log_func = {
            "DEBUG": logger.debug,
            "INFO": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "CRITICAL": logger.critical,
        }.get(severity.upper(), logger.info)

        log_func(log_msg)


# Global audit instance for convenience
audit = SecurityAudit()
