"""Audit logging for sandbox security events."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class AuditEventType(Enum):
    """Types of security audit events."""

    FILE_ACCESS_DENIED = "file_access_denied"
    COMMAND_BLOCKED = "command_blocked"
    PATH_TRAVERSAL_ATTEMPT = "path_traversal_attempt"
    SYMLINK_ESCAPE_ATTEMPT = "symlink_escape_attempt"
    WORKSPACE_VIOLATION = "workspace_violation"


@dataclass
class AuditEvent:
    """Represents a security audit event."""

    event_type: AuditEventType
    timestamp: datetime
    details: dict[str, Any]
    session_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for logging."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "session_key": self.session_key,
            "details": self.details,
        }

    def __str__(self) -> str:
        """Format event for human-readable logging."""
        details_str = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
        session_info = f" [session={self.session_key}]" if self.session_key else ""
        return f"[SECURITY] {self.event_type.value}: {details_str}{session_info}"


class AuditLogger:
    """Logger for sandbox security audit events."""

    def __init__(self, log_file: Path | None = None, enabled: bool = True):
        self.enabled = enabled
        self.log_file = log_file

    def _log_event(self, event: AuditEvent) -> None:
        """Log an audit event to all configured outputs."""
        if not self.enabled:
            return

        # Always log to standard logger at warning level
        logger.warning(str(event))

        # Optionally log to file
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"{event.to_dict()}\n")
            except Exception as e:
                logger.error(f"Failed to write audit log: {e}")

    def log_file_access_denied(
        self,
        path: str,
        reason: str,
        allowed_dir: Path | None = None,
        session_key: str | None = None,
    ) -> None:
        """Log a file access denial event."""
        event = AuditEvent(
            event_type=AuditEventType.FILE_ACCESS_DENIED,
            timestamp=datetime.now(),
            details={
                "path": path,
                "reason": reason,
                "allowed_dir": str(allowed_dir) if allowed_dir else None,
            },
            session_key=session_key,
        )
        self._log_event(event)

    def log_command_blocked(
        self,
        command: str,
        reason: str,
        pattern_matched: str | None = None,
        session_key: str | None = None,
    ) -> None:
        """Log a blocked command execution attempt."""
        event = AuditEvent(
            event_type=AuditEventType.COMMAND_BLOCKED,
            timestamp=datetime.now(),
            details={
                "command": command,
                "reason": reason,
                "pattern_matched": pattern_matched,
            },
            session_key=session_key,
        )
        self._log_event(event)

    def log_path_traversal_attempt(
        self,
        path: str,
        resolved_path: Path | None = None,
        allowed_dir: Path | None = None,
        session_key: str | None = None,
    ) -> None:
        """Log a path traversal attempt."""
        event = AuditEvent(
            event_type=AuditEventType.PATH_TRAVERSAL_ATTEMPT,
            timestamp=datetime.now(),
            details={
                "path": path,
                "resolved_path": str(resolved_path) if resolved_path else None,
                "allowed_dir": str(allowed_dir) if allowed_dir else None,
            },
            session_key=session_key,
        )
        self._log_event(event)

    def log_symlink_escape_attempt(
        self,
        path: str,
        symlink_target: Path,
        allowed_dir: Path | None = None,
        session_key: str | None = None,
    ) -> None:
        """Log a symbolic link escape attempt."""
        event = AuditEvent(
            event_type=AuditEventType.SYMLINK_ESCAPE_ATTEMPT,
            timestamp=datetime.now(),
            details={
                "path": path,
                "symlink_target": str(symlink_target),
                "allowed_dir": str(allowed_dir) if allowed_dir else None,
            },
            session_key=session_key,
        )
        self._log_event(event)

    def log_workspace_violation(
        self,
        operation: str,
        attempted_path: str,
        workspace: Path | None = None,
        session_key: str | None = None,
    ) -> None:
        """Log a workspace boundary violation."""
        event = AuditEvent(
            event_type=AuditEventType.WORKSPACE_VIOLATION,
            timestamp=datetime.now(),
            details={
                "operation": operation,
                "attempted_path": attempted_path,
                "workspace": str(workspace) if workspace else None,
            },
            session_key=session_key,
        )
        self._log_event(event)


# Global audit logger instance
_global_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _global_audit_logger
    if _global_audit_logger is None:
        _global_audit_logger = AuditLogger()
    return _global_audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """Set the global audit logger instance."""
    global _global_audit_logger
    _global_audit_logger = logger
