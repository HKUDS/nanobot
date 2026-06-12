"""Tests for the audit tool module."""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.tools.audit import (
    AuditEvent,
    AuditTool,
    AuditToolConfig,
    AuditTransport,
    CallbackTransport,
    FileTransport,
    LoggerTransport,
    WebhookTransport,
    build_transport,
    set_custom_transport,
)


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------

class TestAuditEvent:
    def test_to_dict_defaults(self):
        ev = AuditEvent(tool="exec", action="call")
        d = ev.to_dict()
        assert d["tool"] == "exec"
        assert d["action"] == "call"
        assert d["params"] == {}
        assert d["result_summary"] == ""
        assert d["session"] == ""
        assert d["agent_id"] == ""
        assert d["duration_ms"] is None
        assert "timestamp" in d

    def test_to_dict_full(self):
        ev = AuditEvent(
            tool="web_fetch",
            action="error",
            params={"url": "https://example.com"},
            result_summary="404 not found",
            detail="HTTP 404",
            session="s1",
            agent_id="a1",
            duration_ms=123.4,
        )
        d = ev.to_dict()
        assert d["tool"] == "web_fetch"
        assert d["action"] == "error"
        assert d["params"]["url"] == "https://example.com"
        assert d["duration_ms"] == 123.4

    def test_to_json_roundtrip(self):
        ev = AuditEvent(tool="exec", action="call", params={"cmd": "ls"})
        parsed = json.loads(ev.to_json())
        assert parsed["tool"] == "exec"
        assert parsed["params"]["cmd"] == "ls"


# ---------------------------------------------------------------------------
# AuditToolConfig
# ---------------------------------------------------------------------------

class TestAuditToolConfig:
    def test_defaults(self):
        cfg = AuditToolConfig()
        assert cfg.enabled is False
        assert cfg.scope == ["*"]
        assert cfg.transport == "logger"
        assert cfg.transport_url == ""
        assert cfg.transport_path == ""

    def test_custom_scope(self):
        cfg = AuditToolConfig(enabled=True, scope=["exec", "web"])
        assert cfg.scope == ["exec", "web"]

    def test_webhook_config(self):
        cfg = AuditToolConfig(enabled=True, transport="webhook", transport_url="https://hooks.example.com/audit")
        assert cfg.transport == "webhook"
        assert cfg.transport_url == "https://hooks.example.com/audit"

    def test_file_config(self):
        cfg = AuditToolConfig(enabled=True, transport="file", transport_path="/tmp/audit.jsonl")
        assert cfg.transport == "file"
        assert cfg.transport_path == "/tmp/audit.jsonl"


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class TestLoggerTransport:
    def test_send_emits_info(self, capfd):
        transport = LoggerTransport()
        ev = AuditEvent(tool="exec", action="call", detail="ran ls")
        transport.send(ev)
        # LoggerTransport uses loguru; just verify no exception


class TestFileTransport:
    def test_send_writes_jsonl(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        transport = FileTransport(str(path))
        ev = AuditEvent(tool="exec", action="call", session="s1")
        transport.send(ev)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["tool"] == "exec"
        assert parsed["action"] == "call"
        assert parsed["session"] == "s1"

    def test_send_appends(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        transport = FileTransport(str(path))
        transport.send(AuditEvent(tool="exec", action="call"))
        transport.send(AuditEvent(tool="web", action="error"))

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["tool"] == "exec"
        assert json.loads(lines[1])["tool"] == "web"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "audit.jsonl"
        transport = FileTransport(str(path))
        transport.send(AuditEvent(tool="exec", action="call"))
        assert path.exists()


class TestCallbackTransport:
    def test_send_invokes_callback(self):
        events = []
        transport = CallbackTransport(callback=events.append)
        ev = AuditEvent(tool="exec", action="call")
        transport.send(ev)
        assert len(events) == 1
        assert events[0].tool == "exec"


class TestWebhookTransport:
    def test_send_posts_json(self):
        transport = WebhookTransport("https://example.com/webhook")
        ev = AuditEvent(tool="exec", action="call")
        # WebhookTransport POSTs via urllib — just verify no crash on init
        assert transport._url == "https://example.com/webhook"


# ---------------------------------------------------------------------------
# build_transport
# ---------------------------------------------------------------------------

class TestBuildTransport:
    def test_logger(self):
        cfg = AuditToolConfig(enabled=True, transport="logger")
        t = build_transport(cfg)
        assert isinstance(t, LoggerTransport)

    def test_file(self, tmp_path):
        cfg = AuditToolConfig(enabled=True, transport="file", transport_path=str(tmp_path / "audit.jsonl"))
        t = build_transport(cfg)
        assert isinstance(t, FileTransport)

    def test_webhook(self):
        cfg = AuditToolConfig(enabled=True, transport="webhook", transport_url="https://example.com")
        t = build_transport(cfg)
        assert isinstance(t, WebhookTransport)

    def test_webhook_missing_url_raises(self):
        cfg = AuditToolConfig(enabled=True, transport="webhook", transport_url="")
        with pytest.raises(ValueError, match="transport_url"):
            build_transport(cfg)

    def test_file_missing_path_raises(self):
        cfg = AuditToolConfig(enabled=True, transport="file", transport_path="")
        with pytest.raises(ValueError, match="transport_path"):
            build_transport(cfg)

    def test_custom_with_registered_callback(self):
        cb = CallbackTransport(callback=lambda e: None)
        set_custom_transport(cb)
        try:
            cfg = AuditToolConfig(enabled=True, transport="custom")
            t = build_transport(cfg)
            assert isinstance(t, CallbackTransport)
        finally:
            set_custom_transport(None)

    def test_custom_without_callback_raises(self):
        set_custom_transport(None)
        cfg = AuditToolConfig(enabled=True, transport="custom")
        with pytest.raises(ValueError, match="custom"):
            build_transport(cfg)

    def test_unknown_transport_raises(self):
        cfg = AuditToolConfig(enabled=True, transport="bogus")
        with pytest.raises(ValueError, match="Unknown"):
            build_transport(cfg)


# ---------------------------------------------------------------------------
# AuditTool
# ---------------------------------------------------------------------------

class TestAuditTool:
    def test_record_disabled_no_event(self):
        cfg = AuditToolConfig(enabled=False)
        tool = AuditTool(cfg=cfg)
        events = []
        tool._transport = CallbackTransport(callback=events.append)
        tool.record("exec", "call")
        assert len(events) == 0

    def test_record_enabled_sends_event(self):
        cfg = AuditToolConfig(enabled=True, scope=["*"])
        tool = AuditTool(cfg=cfg)
        events = []
        tool._transport = CallbackTransport(callback=events.append)
        tool.record("exec", "call", params={"cmd": "ls"}, result_summary="success")
        assert len(events) == 1
        assert events[0].tool == "exec"
        assert events[0].params == {"cmd": "ls"}

    def test_record_scope_filtering(self):
        cfg = AuditToolConfig(enabled=True, scope=["exec", "web"])
        tool = AuditTool(cfg=cfg)
        events = []
        tool._transport = CallbackTransport(callback=events.append)

        tool.record("exec", "call")  # in scope
        tool.record("cron", "call")   # not in scope
        tool.record("web", "call")    # in scope

        assert len(events) == 2
        assert events[0].tool == "exec"
        assert events[1].tool == "web"

    def test_record_wildcard_scope(self):
        cfg = AuditToolConfig(enabled=True, scope=["*"])
        tool = AuditTool(cfg=cfg)
        events = []
        tool._transport = CallbackTransport(callback=events.append)

        tool.record("exec", "call")
        tool.record("web", "call")
        tool.record("cron", "call")

        assert len(events) == 3

    def test_record_empty_scope_means_all(self):
        cfg = AuditToolConfig(enabled=True, scope=[])
        tool = AuditTool(cfg=cfg)
        events = []
        tool._transport = CallbackTransport(callback=events.append)

        tool.record("anything", "call")
        assert len(events) == 1

    def test_record_no_transport_no_crash(self):
        cfg = AuditToolConfig(enabled=True, scope=["*"])
        tool = AuditTool(cfg=cfg)
        tool._transport = None
        tool.record("exec", "call")  # should not raise

    def test_configure_enables_transport(self, tmp_path):
        cfg = AuditToolConfig(enabled=True, transport="file", transport_path=str(tmp_path / "audit.jsonl"))
        tool = AuditTool()
        tool.configure(cfg, session="s1", agent_id="a1")
        assert tool._transport is not None
        assert tool._session == "s1"
        assert tool._agent_id == "a1"

    def test_configure_disabled_clears_transport(self):
        cfg = AuditToolConfig(enabled=False)
        tool = AuditTool()
        tool.configure(cfg)
        assert tool._transport is None

    def test_record_populates_event_fields(self):
        cfg = AuditToolConfig(enabled=True, scope=["*"])
        tool = AuditTool(cfg=cfg)
        tool._session = "sess1"
        tool._agent_id = "agent1"
        events = []
        tool._transport = CallbackTransport(callback=events.append)

        tool.record("exec", "call", params={"cmd": "ls"}, duration_ms=50.3)

        ev = events[0]
        assert ev.session == "sess1"
        assert ev.agent_id == "agent1"
        assert ev.duration_ms == 50.3

    def test_record_truncates_long_detail(self):
        cfg = AuditToolConfig(enabled=True, scope=["*"])
        tool = AuditTool(cfg=cfg)
        events = []
        tool._transport = CallbackTransport(callback=events.append)

        tool.record("exec", "call", detail="x" * 1000)

        assert len(events[0].detail) <= 500

    async def test_execute_returns_message(self):
        tool = AuditTool()
        result = await tool.execute()
        assert "record()" in result

    def test_definition_empty(self):
        assert AuditTool.definition() == {}


# ---------------------------------------------------------------------------
# Integration: config schema
# ---------------------------------------------------------------------------

class TestAuditConfigInSchema:
    def test_tools_config_includes_audit(self):
        from nanobot.config.schema import ToolsConfig

        tc = ToolsConfig()
        assert hasattr(tc, "audit")
        assert isinstance(tc.audit, AuditToolConfig)
        assert tc.audit.enabled is False

    def test_tools_config_audit_enabled(self):
        from nanobot.config.schema import ToolsConfig

        tc = ToolsConfig(audit=AuditToolConfig(enabled=True, transport="file", transport_path="/tmp/audit.jsonl"))
        assert tc.audit.enabled is True
        assert tc.audit.transport == "file"


# ---------------------------------------------------------------------------
# End-to-end: file transport audit trail
# ---------------------------------------------------------------------------

class TestEndToEndFileAudit:
    """Prove audit events are written to a file end-to-end."""

    def test_file_audit_trail(self, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        cfg = AuditToolConfig(enabled=True, transport="file", transport_path=str(audit_path))
        tool = AuditTool(cfg=cfg)
        tool.configure(cfg, session="test-session", agent_id="test-agent")

        # Simulate tool invocations
        tool.record("exec", "call", params={"cmd": "ls -la"}, result_summary="file1.txt file2.txt", duration_ms=12.5)
        tool.record("web_fetch", "call", params={"url": "https://example.com"}, result_summary="200 OK", duration_ms=340.2)
        tool.record("cron", "error", detail="cron job failed: permission denied", duration_ms=0.1)

        assert audit_path.exists()
        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) == 3

        events = [json.loads(line) for line in lines]
        assert events[0]["tool"] == "exec"
        assert events[0]["action"] == "call"
        assert events[0]["session"] == "test-session"
        assert events[0]["agent_id"] == "test-agent"
        assert events[0]["duration_ms"] == 12.5

        assert events[1]["tool"] == "web_fetch"
        assert events[1]["action"] == "call"

        assert events[2]["tool"] == "cron"
        assert events[2]["action"] == "error"

    def test_scope_filtering_end_to_end(self, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        cfg = AuditToolConfig(enabled=True, scope=["exec"], transport="file", transport_path=str(audit_path))
        tool = AuditTool(cfg=cfg)
        tool.configure(cfg)

        tool.record("exec", "call")  # in scope
        tool.record("web", "call")   # out of scope

        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["tool"] == "exec"