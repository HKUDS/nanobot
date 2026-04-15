"""Tests for heartbeat outbound message logging and session injection."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.heartbeat.message_log import (
    extract_outbound_messages,
    inject_into_recipient_sessions,
    persist_outbound_messages,
    write_message_log,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_session(messages):
    return SimpleNamespace(messages=messages)


class FakeSessionManager:
    """In-memory session manager for testing."""

    def __init__(self):
        self.sessions: dict[str, SimpleNamespace] = {}
        self.save_calls: list[str] = []

    def get_or_create(self, key: str):
        if key not in self.sessions:
            self.sessions[key] = _make_session([])
        return self.sessions[key]

    def save(self, session):
        for k, v in self.sessions.items():
            if v is session:
                self.save_calls.append(k)
                break


def _msg_with_message_tool(channel, chat_id, content, timestamp="2026-04-15T07:04:00"):
    """Build an assistant message with a message tool call."""
    return {
        "role": "assistant",
        "content": "",
        "timestamp": timestamp,
        "tool_calls": [{
            "id": "tc1",
            "type": "function",
            "function": {
                "name": "message",
                "arguments": json.dumps({
                    "channel": channel,
                    "chat_id": chat_id,
                    "content": content,
                }),
            },
        }],
    }


def _msg_with_exec_tool(command, timestamp="2026-04-15T07:03:00"):
    """Build an assistant message with an exec tool call (not message)."""
    return {
        "role": "assistant",
        "content": "",
        "timestamp": timestamp,
        "tool_calls": [{
            "id": "tc2",
            "type": "function",
            "function": {
                "name": "exec",
                "arguments": json.dumps({"command": command}),
            },
        }],
    }


# ── extract_outbound_messages ───────────────────────────────────────────────

class TestExtractOutboundMessages:
    def test_extracts_message_tool_calls(self):
        messages = [
            _msg_with_message_tool("whatsapp", "123@lid", "Good morning!"),
        ]
        result = extract_outbound_messages(messages, "Morning briefing")
        assert len(result) == 1
        assert result[0]["channel"] == "whatsapp"
        assert result[0]["chat_id"] == "123@lid"
        assert result[0]["content"] == "Good morning!"
        assert result[0]["task"] == "Morning briefing"
        assert result[0]["timestamp"] == "2026-04-15T07:04:00"

    def test_ignores_non_message_tools(self):
        messages = [
            _msg_with_exec_tool("python tools/gmail_fetch.py"),
        ]
        result = extract_outbound_messages(messages, "Gmail scan")
        assert result == []

    def test_extracts_multiple_recipients(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "timestamp": "2026-04-15T07:04:00",
                "tool_calls": [
                    {
                        "id": "tc1", "type": "function",
                        "function": {
                            "name": "message",
                            "arguments": json.dumps({
                                "channel": "whatsapp", "chat_id": "user_a",
                                "content": "Hello A",
                            }),
                        },
                    },
                    {
                        "id": "tc2", "type": "function",
                        "function": {
                            "name": "message",
                            "arguments": json.dumps({
                                "channel": "whatsapp", "chat_id": "user_b",
                                "content": "Hello B",
                            }),
                        },
                    },
                ],
            },
        ]
        result = extract_outbound_messages(messages, "Morning briefing")
        assert len(result) == 2
        assert result[0]["chat_id"] == "user_a"
        assert result[1]["chat_id"] == "user_b"

    def test_since_idx_skips_earlier_messages(self):
        messages = [
            _msg_with_message_tool("whatsapp", "old_user", "Old msg", "2026-04-14T07:00:00"),
            _msg_with_message_tool("whatsapp", "new_user", "New msg", "2026-04-15T07:00:00"),
        ]
        result = extract_outbound_messages(messages, "task", since_idx=1)
        assert len(result) == 1
        assert result[0]["chat_id"] == "new_user"

    def test_handles_invalid_json_arguments(self):
        messages = [{
            "role": "assistant",
            "content": "",
            "timestamp": "2026-04-15T07:04:00",
            "tool_calls": [{
                "id": "tc1", "type": "function",
                "function": {"name": "message", "arguments": "not json"},
            }],
        }]
        result = extract_outbound_messages(messages, "task")
        assert result == []

    def test_handles_messages_without_tool_calls(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = extract_outbound_messages(messages, "task")
        assert result == []

    def test_mixed_tools_only_extracts_message(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "timestamp": "2026-04-15T07:04:00",
                "tool_calls": [
                    {"id": "tc1", "type": "function",
                     "function": {"name": "exec", "arguments": json.dumps({"command": "ls"})}},
                    {"id": "tc2", "type": "function",
                     "function": {"name": "message", "arguments": json.dumps({
                         "channel": "telegram", "chat_id": "999", "content": "Alert!",
                     })}},
                    {"id": "tc3", "type": "function",
                     "function": {"name": "read_file", "arguments": json.dumps({"path": "/tmp/x"})}},
                ],
            },
        ]
        result = extract_outbound_messages(messages, "Gmail scan")
        assert len(result) == 1
        assert result[0]["content"] == "Alert!"


# ── write_message_log ──────────────────────────────────────────────────────

class TestWriteMessageLog:
    def test_writes_entries_to_file(self, tmp_path):
        log_path = tmp_path / "state" / "message_log.jsonl"
        entries = [
            {"timestamp": "2026-04-15T07:04:00", "task": "briefing",
             "channel": "whatsapp", "chat_id": "123", "content": "Hello"},
        ]
        write_message_log(log_path, entries)
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["content"] == "Hello"

    def test_appends_to_existing_file(self, tmp_path):
        log_path = tmp_path / "message_log.jsonl"
        log_path.write_text('{"existing": true}\n')
        write_message_log(log_path, [{"new": True}])
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_noop_with_empty_entries(self, tmp_path):
        log_path = tmp_path / "message_log.jsonl"
        write_message_log(log_path, [])
        assert not log_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        log_path = tmp_path / "deep" / "nested" / "log.jsonl"
        write_message_log(log_path, [{"x": 1}])
        assert log_path.exists()


# ── inject_into_recipient_sessions ─────────────────────────────────────────

class TestInjectIntoRecipientSessions:
    def test_injects_into_correct_session(self):
        mgr = FakeSessionManager()
        entries = [
            {"timestamp": "2026-04-15T07:04:00", "task": "Morning briefing",
             "channel": "whatsapp", "chat_id": "246@lid", "content": "Good morning!"},
        ]
        inject_into_recipient_sessions(entries, mgr)

        session = mgr.sessions["whatsapp:246@lid"]
        assert len(session.messages) == 1
        msg = session.messages[0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Good morning!"
        assert msg["_source"] == "heartbeat"
        assert msg["_task"] == "Morning briefing"

    def test_injects_into_separate_sessions_per_recipient(self):
        mgr = FakeSessionManager()
        entries = [
            {"timestamp": "T1", "task": "briefing",
             "channel": "whatsapp", "chat_id": "user_a", "content": "Hi A"},
            {"timestamp": "T1", "task": "briefing",
             "channel": "whatsapp", "chat_id": "user_b", "content": "Hi B"},
        ]
        inject_into_recipient_sessions(entries, mgr)

        assert len(mgr.sessions) == 2
        assert mgr.sessions["whatsapp:user_a"].messages[0]["content"] == "Hi A"
        assert mgr.sessions["whatsapp:user_b"].messages[0]["content"] == "Hi B"

    def test_saves_each_recipient_session(self):
        mgr = FakeSessionManager()
        entries = [
            {"timestamp": "T1", "task": "t", "channel": "whatsapp", "chat_id": "a", "content": "x"},
            {"timestamp": "T1", "task": "t", "channel": "telegram", "chat_id": "b", "content": "y"},
        ]
        inject_into_recipient_sessions(entries, mgr)
        assert "whatsapp:a" in mgr.save_calls
        assert "telegram:b" in mgr.save_calls

    def test_skips_entries_without_channel_or_chat_id(self):
        mgr = FakeSessionManager()
        entries = [
            {"timestamp": "T1", "task": "t", "channel": "", "chat_id": "123", "content": "x"},
            {"timestamp": "T1", "task": "t", "channel": "whatsapp", "chat_id": "", "content": "y"},
        ]
        inject_into_recipient_sessions(entries, mgr)
        assert len(mgr.sessions) == 0

    def test_appends_to_existing_session_messages(self):
        mgr = FakeSessionManager()
        # Pre-populate session with an existing message
        existing = mgr.get_or_create("whatsapp:123")
        existing.messages.append({"role": "user", "content": "Hey Homer"})

        entries = [
            {"timestamp": "T1", "task": "briefing",
             "channel": "whatsapp", "chat_id": "123", "content": "Morning!"},
        ]
        inject_into_recipient_sessions(entries, mgr)

        assert len(existing.messages) == 2
        assert existing.messages[0]["role"] == "user"
        assert existing.messages[1]["role"] == "assistant"
        assert existing.messages[1]["content"] == "Morning!"


# ── persist_outbound_messages (integration) ────────────────────────────────

class TestPersistOutboundMessages:
    def test_full_flow(self, tmp_path):
        log_path = tmp_path / "message_log.jsonl"
        mgr = FakeSessionManager()
        session = _make_session([
            {"role": "user", "content": "Morning briefing (system)"},
            _msg_with_exec_tool("python tools/morning_briefing.py"),
            _msg_with_message_tool("whatsapp", "246@lid", "Good morning Ebby!"),
            _msg_with_message_tool("whatsapp", "105@lid", "Good morning Seun!"),
        ])

        entries = persist_outbound_messages(session, "Morning briefing", log_path, mgr)

        # Returns extracted entries
        assert len(entries) == 2

        # Log file written
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["chat_id"] == "246@lid"
        assert json.loads(lines[1])["chat_id"] == "105@lid"

        # Recipient sessions injected
        assert "whatsapp:246@lid" in mgr.sessions
        assert "whatsapp:105@lid" in mgr.sessions
        assert mgr.sessions["whatsapp:246@lid"].messages[0]["content"] == "Good morning Ebby!"
        assert mgr.sessions["whatsapp:105@lid"].messages[0]["content"] == "Good morning Seun!"

    def test_since_idx_only_processes_new_messages(self, tmp_path):
        log_path = tmp_path / "message_log.jsonl"
        mgr = FakeSessionManager()
        session = _make_session([
            _msg_with_message_tool("whatsapp", "old", "Already logged"),
            _msg_with_message_tool("whatsapp", "new", "Fresh message"),
        ])

        entries = persist_outbound_messages(session, "task", log_path, mgr, since_idx=1)

        assert len(entries) == 1
        assert entries[0]["chat_id"] == "new"
        assert "whatsapp:old" not in mgr.sessions
        assert "whatsapp:new" in mgr.sessions

    def test_no_message_tools_produces_no_side_effects(self, tmp_path):
        log_path = tmp_path / "message_log.jsonl"
        mgr = FakeSessionManager()
        session = _make_session([
            {"role": "user", "content": "Gmail scan (system)"},
            _msg_with_exec_tool("python tools/gmail_fetch.py"),
            {"role": "assistant", "content": "No actionable emails."},
        ])

        entries = persist_outbound_messages(session, "Gmail scan", log_path, mgr)

        assert entries == []
        assert not log_path.exists()
        assert len(mgr.sessions) == 0
