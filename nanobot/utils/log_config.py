"""Shared configuration for human-readable nanobot logs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DDTHH:mm:ss.SSSZZ}</green> | "
    "<level>{level: <7}</level> | "
    "<cyan>{extra[channel]}</cyan> | "
    "<cyan>{extra[log_context]}</cyan> | "
    "<level>{extra[safe_message]}</level>"
)


def _single_line(value: object) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def prepare_log_record(record: "Record") -> bool:
    """Populate display fields without altering the structured log record."""
    extra = record["extra"]
    extra.setdefault("channel", "-")
    extra["channel"] = _single_line(extra["channel"])
    extra["safe_message"] = _single_line(record["message"])

    context: list[str] = []
    for label, field in (
        ("request", "request_id"),
        ("turn", "turn_id"),
        ("session", "session_key"),
    ):
        value = extra.get(field)
        if value not in (None, "", "-"):
            context.append(f"{label}={_single_line(value)}")
    extra["log_context"] = " ".join(context) or "-"
    return True


def add_console_log_sink(stream: Any, *, level: str = "INFO") -> int:
    """Add the standard nanobot console sink and return its handler id."""
    return logger.add(
        stream,
        format=LOG_FORMAT,
        level=level,
        colorize=None,
        filter=prepare_log_record,
    )


def configure_console_logging(stream: Any, *, level: str = "INFO") -> int:
    """Replace existing handlers with the standard nanobot console sink."""
    logger.remove()
    return add_console_log_sink(stream, level=level)
