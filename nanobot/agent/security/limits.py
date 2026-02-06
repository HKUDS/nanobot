"""Resource limits for DoS prevention.

This module defines resource limits to prevent denial-of-service attacks
through resource exhaustion. These limits protect against:

- Large file operations that could exhaust memory
- Oversized HTTP responses that could exhaust memory
- Queue flooding that could exhaust memory
- Session bloat that could exhaust storage

All limits can be configured via environment variables.
"""
import os
from loguru import logger

# File limits
MAX_FILE_READ_SIZE = int(os.environ.get("NANOBOT_MAX_FILE_READ_SIZE", 10 * 1024 * 1024))  # 10MB
MAX_FILE_WRITE_SIZE = int(os.environ.get("NANOBOT_MAX_FILE_WRITE_SIZE", 10 * 1024 * 1024))  # 10MB

# Web limits
MAX_RESPONSE_SIZE = int(os.environ.get("NANOBOT_MAX_RESPONSE_SIZE", 5 * 1024 * 1024))  # 5MB

# Queue limits
MAX_QUEUE_SIZE = int(os.environ.get("NANOBOT_MAX_QUEUE_SIZE", 1000))

# Session limits
MAX_SESSION_MESSAGES = int(os.environ.get("NANOBOT_MAX_SESSION_MESSAGES", 1000))
MAX_SESSION_SIZE = int(os.environ.get("NANOBOT_MAX_SESSION_SIZE", 50 * 1024 * 1024))  # 50MB


def check_file_size(size: int, operation: str) -> tuple[bool, str]:
    """Check if file size is within limits.

    Args:
        size: The size of the file in bytes.
        operation: Either "read" or "write".

    Returns:
        Tuple of (allowed, error_message). If allowed, error_message is empty.
    """
    limit = MAX_FILE_READ_SIZE if operation == "read" else MAX_FILE_WRITE_SIZE
    if size > limit:
        logger.warning(f"DOS: File {operation} blocked - size {size} exceeds limit {limit}")
        return False, f"File too large ({size} bytes). Maximum allowed: {limit} bytes"
    return True, ""


def check_content_size(size: int, limit: int = MAX_RESPONSE_SIZE) -> tuple[bool, str]:
    """Check if content size is within limit.

    Args:
        size: The size of the content in bytes.
        limit: The maximum allowed size (defaults to MAX_RESPONSE_SIZE).

    Returns:
        Tuple of (allowed, error_message). If allowed, error_message is empty.
    """
    if size > limit:
        logger.warning(f"DOS: Content blocked - size {size} exceeds limit {limit}")
        return False, f"Content too large ({size} bytes). Maximum allowed: {limit} bytes"
    return True, ""


def check_queue_size(current_size: int, max_size: int = MAX_QUEUE_SIZE) -> tuple[bool, str]:
    """Check if adding to queue would exceed limit.

    Args:
        current_size: Current number of items in queue.
        max_size: Maximum allowed queue size.

    Returns:
        Tuple of (allowed, error_message). If allowed, error_message is empty.
    """
    if current_size >= max_size:
        logger.warning(f"DOS: Queue full - current {current_size} at limit {max_size}")
        return False, f"Queue full ({current_size} items). Maximum allowed: {max_size}"
    return True, ""


def check_session_messages(message_count: int, max_messages: int = MAX_SESSION_MESSAGES) -> tuple[bool, str]:
    """Check if session message count is within limit.

    Args:
        message_count: Current number of messages in session.
        max_messages: Maximum allowed messages per session.

    Returns:
        Tuple of (allowed, error_message). If allowed, error_message is empty.
    """
    if message_count >= max_messages:
        logger.warning(f"DOS: Session messages limit reached - {message_count} at limit {max_messages}")
        return False, f"Session message limit reached ({message_count}). Maximum allowed: {max_messages}"
    return True, ""


def check_session_size(session_size: int, max_size: int = MAX_SESSION_SIZE) -> tuple[bool, str]:
    """Check if session size is within limit.

    Args:
        session_size: Current session size in bytes.
        max_size: Maximum allowed session size.

    Returns:
        Tuple of (allowed, error_message). If allowed, error_message is empty.
    """
    if session_size >= max_size:
        logger.warning(f"DOS: Session size limit reached - {session_size} at limit {max_size}")
        return False, f"Session size limit reached ({session_size} bytes). Maximum allowed: {max_size} bytes"
    return True, ""
