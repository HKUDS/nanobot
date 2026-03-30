"""Tests for _save_turn reasoning field sanitization."""

from unittest.mock import patch, MagicMock
from nanobot.session.manager import Session


def test_save_turn_strips_reasoning_content():
    """reasoning_content and thinking_blocks must be stripped before persisting to session."""
    session = Session(key="test:123")
    assert len(session.messages) == 0

    # Import and patch AgentLoop minimally — avoid full __init__
    from nanobot.agent.loop import AgentLoop

    loop = object.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = 10000

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there", "reasoning_content": "user said hello"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_1", "type": "function", "function": {"name": "message", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc_1", "name": "message", "content": "sent"},
        {"role": "assistant", "content": "Done!", "thinking_blocks": [{"type": "thinking", "thinking": "completed"}]},
    ]

    loop._save_turn(session, messages, skip=0)

    for msg in session.messages:
        assert "reasoning_content" not in msg, f"reasoning_content leaked into session: {msg}"
        assert "thinking_blocks" not in msg, f"thinking_blocks leaked into session: {msg}"
        assert "extra_content" not in msg, f"extra_content leaked into session: {msg}"


def test_save_turn_preserves_standard_fields():
    """Standard message fields (role, content, tool_calls, etc.) must be preserved."""
    session = Session(key="test:456")

    from nanobot.agent.loop import AgentLoop
    loop = object.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = 10000

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi", "tool_calls": [{"id": "tc_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc_1", "name": "test", "content": "ok"},
    ]

    loop._save_turn(session, messages, skip=0)

    assert len(session.messages) == 3
    assert session.messages[0]["role"] == "user"
    assert session.messages[1]["role"] == "assistant"
    assert "tool_calls" in session.messages[1]
    assert session.messages[2]["role"] == "tool"
