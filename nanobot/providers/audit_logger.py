"""Audit logger for tracking API requests and responses.

This module logs all LLM API interactions with timestamps, model info,
token usage, messages, and responses for auditing and statistics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir, get_data_path


@dataclass
class APILogEntry:
    """A single API log entry."""

    # Request info
    timestamp: str
    model: str
    provider: str

    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Messages (truncated for size)
    request_messages: str | None = None
    response_content: str | None = None
    tool_calls: list[str] | None = None

    # Status
    success: bool = True
    error: str | None = None
    finish_reason: str | None = None

    # Request duration
    duration_ms: float | None = None

    @staticmethod
    def _truncate(text: str, max_len: int = 2000) -> str:
        """Truncate text to max length."""
        if len(text) <= max_len:
            return text
        return text[:max_len] + "... [truncated]"

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> str:
        """Format messages for logging, truncating long content."""
        formatted = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False)
            if content and len(str(content)) > 500:
                content = APILogEntry._truncate(str(content), 500)
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)

    @classmethod
    def from_request(
        cls,
        model: str,
        provider: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> APILogEntry:
        """Create a log entry from request data."""
        return cls(
            timestamp=datetime.now().isoformat(),
            model=model,
            provider=provider,
            request_messages=cls._format_messages(messages),
        )

    def with_response(
        self,
        content: str | None,
        tool_calls: list[str] | None,
        usage: dict[str, int] | None,
        finish_reason: str | None,
        duration_ms: float | None = None,
    ) -> APILogEntry:
        """Add response data to the entry."""
        if content:
            self.response_content = self._truncate(content, 2000) if len(content) > 2000 else content
        if tool_calls:
            self.tool_calls = tool_calls[:10]  # Limit to 10 tools
        if usage:
            self.prompt_tokens = usage.get("prompt_tokens", 0)
            self.completion_tokens = usage.get("completion_tokens", 0)
            self.total_tokens = usage.get("total_tokens", 0)
        self.finish_reason = finish_reason
        self.duration_ms = duration_ms
        return self

    def with_error(self, error: str) -> APILogEntry:
        """Mark entry as failed with error."""
        self.success = False
        self.error = self._truncate(error, 500) if len(error) > 500 else error
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)


class APILogger:
    """Logger for tracking API interactions."""

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or self._get_default_log_dir()
        ensure_dir(self.log_dir)
        self._current_log_file: Path | None = None
        self._entries: list[APILogEntry] = []
        self._flush_threshold = 1  # Flush after each entry for reliability

    @staticmethod
    def _get_default_log_dir() -> Path:
        """Get the default log directory."""
        return get_data_path() / "api_logs"

    def _get_log_file(self) -> Path:
        """Get the log file for today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"api_logs_{today}.jsonl"

    def _flush(self) -> None:
        """Flush buffered entries to disk."""
        if not self._entries:
            return

        log_file = self._get_log_file()
        with open(log_file, "a", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False))
                f.write("\n")

        self._entries = []

    def log(self, entry: APILogEntry) -> None:
        """Log an API entry."""
        self._entries.append(entry)
        if len(self._entries) >= self._flush_threshold:
            self._flush()

    def __del__(self):
        """Flush on destruction."""
        try:
            self._flush()
        except Exception:
            pass


# Global logger instance
_logger: APILogger | None = None


def get_logger() -> APILogger:
    """Get the global API logger instance."""
    global _logger
    if _logger is None:
        _logger = APILogger()
    return _logger


def set_logger(logger: APILogger) -> None:
    """Set the global API logger instance (for testing)."""
    global _logger
    _logger = logger


# ============================================================================
# Statistics / Query Functions
# ============================================================================


@dataclass
class APIStats:
    """Aggregated API statistics."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    model_counts: dict[str, int] = None
    provider_counts: dict[str, int] = None
    avg_duration_ms: float | None = None

    def __post_init__(self):
        if self.model_counts is None:
            self.model_counts = {}
        if self.provider_counts is None:
            self.provider_counts = {}


def get_stats(
    days: int = 7,
    log_dir: Path | None = None,
) -> APIStats:
    """
    Get API statistics for the last N days.

    Args:
        days: Number of days to include
        log_dir: Optional log directory override

    Returns:
        APIStats with aggregated data
    """
    from datetime import timedelta

    stats = APIStats()
    log_dir = log_dir or APILogger._get_default_log_dir()

    if not log_dir.exists():
        return stats

    cutoff_date = datetime.now() - timedelta(days=days)
    durations: list[float] = []

    for log_file in sorted(log_dir.glob("api_logs_*.jsonl")):
        try:
            # Parse date from filename
            date_str = log_file.stem.replace("api_logs_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")

            if file_date < cutoff_date:
                continue

            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entry = APILogEntry(**data)

                        stats.total_requests += 1
                        if entry.success:
                            stats.successful_requests += 1
                        else:
                            stats.failed_requests += 1

                        stats.total_prompt_tokens += entry.prompt_tokens
                        stats.total_completion_tokens += entry.completion_tokens
                        stats.total_tokens += entry.total_tokens

                        stats.model_counts[entry.model] = stats.model_counts.get(entry.model, 0) + 1
                        stats.provider_counts[entry.provider] = (
                            stats.provider_counts.get(entry.provider, 0) + 1
                        )

                        if entry.duration_ms is not None:
                            durations.append(entry.duration_ms)

                    except (json.JSONDecodeError, TypeError):
                        continue
        except (ValueError, IOError):
            continue

    if durations:
        stats.avg_duration_ms = sum(durations) / len(durations)

    return stats


def get_recent_entries(
    limit: int = 20,
    log_dir: Path | None = None,
) -> list[APILogEntry]:
    """
    Get the most recent API log entries.

    Args:
        limit: Maximum number of entries to return
        log_dir: Optional log directory override

    Returns:
        List of APILogEntry, most recent first
    """
    entries: list[APILogEntry] = []
    log_dir = log_dir or APILogger._get_default_log_dir()

    if not log_dir.exists():
        return entries

    # Read files in reverse chronological order
    for log_file in sorted(log_dir.glob("api_logs_*.jsonl"), reverse=True):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                # Read all lines from this file
                file_entries = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        file_entries.append(APILogEntry(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue

                # Add to entries in reverse order (most recent first)
                entries.extend(reversed(file_entries))

                if len(entries) >= limit:
                    break

        except IOError:
            continue

    return entries[:limit]
