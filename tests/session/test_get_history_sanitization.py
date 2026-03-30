"""Tests for get_history key filtering."""

from nanobot.session.manager import Session


def test_get_history_filters_reasoning_content():
    """get_history must not return reasoning_content or thinking_blocks."""
    session = Session(key="test:789")
    session.messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi", "reasoning_content": "thinking..."},
        {"role": "assistant", "content": "Done", "thinking_blocks": [{"type": "thinking", "thinking": "hmm"}], "extra_content": "extra"},
    ]

    history = session.get_history(max_messages=0)

    for msg in history:
        assert "reasoning_content" not in msg, f"reasoning_content leaked in history: {msg}"
        assert "thinking_blocks" not in msg, f"thinking_blocks leaked in history: {msg}"
        assert "extra_content" not in msg, f"extra_content leaked in history: {msg}"


def test_get_history_preserves_standard_keys():
    """get_history must preserve role, content, tool_calls, tool_call_id, name."""
    session = Session(key="test:101")
    session.messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc_1", "name": "test", "content": "ok"},
    ]

    history = session.get_history(max_messages=0)

    assert history[0]["role"] == "user"
    assert "tool_calls" in history[1]
    assert history[1]["content"] is None
    assert history[2]["tool_call_id"] == "tc_1"
    assert history[2]["name"] == "test"
