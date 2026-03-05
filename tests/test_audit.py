"""Tests for audit logging functionality."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.agent.tools.audit import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    get_audit_logger,
    set_audit_logger,
)


class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        event = AuditEvent(
            event_type=AuditEventType.FILE_ACCESS_DENIED,
            timestamp="2025-01-01T00:00:00",  # type: ignore
            details={"path": "/etc/passwd", "reason": "outside workspace"},
            session_key="test-session",
        )
        d = event.to_dict()
        assert d["event_type"] == "file_access_denied"
        assert d["session_key"] == "test-session"
        assert d["details"]["path"] == "/etc/passwd"

    def test_event_str(self):
        """Test string representation."""
        event = AuditEvent(
            event_type=AuditEventType.COMMAND_BLOCKED,
            timestamp="2025-01-01T00:00:00",  # type: ignore
            details={"command": "rm -rf /", "reason": "dangerous"},
            session_key=None,
        )
        s = str(event)
        assert "[SECURITY] command_blocked" in s
        assert "rm -rf /" in s


class TestAuditLogger:
    """Tests for AuditLogger class."""

    def test_logger_disabled(self):
        """Test that disabled logger doesn't log."""
        logger = AuditLogger(enabled=False)
        # Should not raise or log
        logger.log_file_access_denied("/test/path", "test reason")
        logger.log_command_blocked("rm -rf /", "dangerous")

    def test_logger_file_output(self):
        """Test logging to file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = Path(f.name)

        try:
            logger = AuditLogger(log_file=log_path, enabled=True)
            logger.log_command_blocked("rm -rf /", "dangerous pattern")

            content = log_path.read_text()
            assert "command_blocked" in content
            assert "rm -rf /" in content
        finally:
            log_path.unlink(missing_ok=True)

    @patch("nanobot.agent.tools.audit.logger")
    def test_logger_calls_standard_logger(self, mock_logger):
        """Test that events are logged via loguru."""
        logger = AuditLogger(enabled=True)
        logger.log_file_access_denied("/test/path", "test reason")

        # Should have called warning
        assert mock_logger.warning.called

    def test_global_audit_logger(self):
        """Test global logger instance management."""
        # Get default logger
        logger1 = get_audit_logger()
        assert logger1 is not None

        # Set a new logger
        custom_logger = AuditLogger(enabled=False)
        set_audit_logger(custom_logger)

        # Get should return custom logger
        logger2 = get_audit_logger()
        assert logger2 is custom_logger

        # Reset to default
        import nanobot.agent.tools.audit as audit_module

        audit_module._global_audit_logger = None

    def test_all_event_types(self):
        """Test all event type logging methods."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = Path(f.name)

        try:
            logger = AuditLogger(log_file=log_path, enabled=True)

            # Test all logging methods
            logger.log_file_access_denied("/etc/passwd", "outside workspace")
            logger.log_command_blocked("rm -rf /", "dangerous", pattern_matched="rm -rf")
            logger.log_path_traversal_attempt(
                path="../../../etc/passwd", resolved_path=Path("/etc/passwd")
            )
            logger.log_symlink_escape_attempt(
                path="/workspace/link", symlink_target=Path("/etc/passwd")
            )
            logger.log_workspace_violation(
                operation="read", attempted_path="/etc/passwd"
            )

            content = log_path.read_text()
            lines = content.strip().split("\n")

            # Should have 5 log entries
            assert len(lines) == 5

            # Verify each event type appears
            event_types = [line for line in lines if "event_type" in line]
            assert "file_access_denied" in content
            assert "command_blocked" in content
            assert "path_traversal_attempt" in content
            assert "symlink_escape_attempt" in content
            assert "workspace_violation" in content
        finally:
            log_path.unlink(missing_ok=True)


class TestAuditEventTypes:
    """Tests for audit event type enumeration."""

    def test_event_types_exist(self):
        """Test all expected event types exist."""
        expected_types = [
            "file_access_denied",
            "command_blocked",
            "path_traversal_attempt",
            "symlink_escape_attempt",
            "workspace_violation",
        ]
        for event_type in expected_types:
            assert hasattr(AuditEventType, event_type.upper())
            assert AuditEventType[event_type.upper()].value == event_type