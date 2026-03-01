"""Enhanced logging configuration for nanobot."""

import sys
from pathlib import Path
from typing import Any

from loguru import logger


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    enable_console: bool = True,
    format_string: str | None = None
) -> None:
    """
    Configure loguru logging with enhanced formatting.
    
    Args:
        level: Log level (TRACE, DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
        enable_console: Whether to output to console
        format_string: Custom format string
    """
    # Remove default handler
    logger.remove()
    
    # Default format with colors for console, plain for file
    if format_string is None:
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        )
    else:
        console_format = file_format = format_string
    
    # Add console handler
    if enable_console:
        logger.add(
            sys.stderr,
            level=level,
            format=console_format,
            colorize=True,
            backtrace=True,
            diagnose=True
        )
    
    # Add file handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            log_path,
            level=level,
            format=file_format,
            rotation="10 MB",
            retention="7 days",
            compression="gz",
            backtrace=True,
            diagnose=True
        )


def setup_agent_logging(verbose: bool = False, log_file: str | None = None) -> None:
    """
    Setup logging specifically for agent operations.
    
    Args:
        verbose: Enable DEBUG/TRACE level logging
        log_file: Optional log file path
    """
    level = "TRACE" if verbose else "INFO"
    
    # Configure with agent-specific format
    configure_logging(
        level=level,
        log_file=log_file,
        enable_console=True,
        format_string=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{extra[session]: <12}</cyan> | "
            "<level>{message}</level>"
        )
    )
    
    # Add session context to logs
    logger.configure(extra={"session": "system"})


def set_session_context(session_key: str) -> None:
    """Set session context for subsequent log messages."""
    logger.configure(extra={"session": session_key.split(":")[-1][:12]})


def get_log_level_from_env() -> str:
    """Get log level from environment variable."""
    import os
    return os.environ.get("LOGURU_LEVEL", "INFO").upper()
