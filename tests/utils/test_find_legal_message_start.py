"""Tests for find_legal_message_start.

Regression test for https://github.com/HKUDS/nanobot/issues/4203
"""

from nanobot.utils.helpers import find_legal_message_start


def test_empty_messages():
    assert find_legal_message_start([]) == 0


def test_single_user_message():
    msgs = [{"role": "user", "content": "hello"}]
    assert find_legal_message_start(msgs) == 0


def test_valid_tool_call_sequence():
    msgs = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "tool_calls": [{"id": "tc1", "name": "f"}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "ok"},
        {"role": "user", "content": "q2"},
    ]
    assert find_legal_message_start(msgs) == 0


def test_orphaned_tool_at_end_does_not_discard_all():
    """Issue #4203: orphaned tool at end should not discard all messages."""
    msgs = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "tool_calls": [{"id": "A"}]},
        {"role": "tool", "tool_call_id": "A"},
        {"role": "user", "content": "q2"},
        {"role": "tool", "tool_call_id": "B"},  # orphaned
    ]
    result = find_legal_message_start(msgs)
    # Before fix: returned 5 (len(msgs)) → empty slice
    # After fix: returns min(5, 4) = 4 → [orphaned tool]
    # Key assertion: does NOT return len(msgs)
    assert result < len(msgs)


def test_orphaned_tool_in_middle():
    """Orphaned tool in the middle — skip past it."""
    msgs = [
        {"role": "user", "content": "q1"},
        {"role": "tool", "tool_call_id": "orphan"},  # orphaned
        {"role": "user", "content": "q2"},
        {"role": "assistant", "tool_calls": [{"id": "tc2"}]},
        {"role": "tool", "tool_call_id": "tc2", "content": "ok"},
    ]
    result = find_legal_message_start(msgs)
    # Should skip past the orphan at index 1
    assert result >= 2
    retained = msgs[result:]
    contents = [m.get("content") for m in retained]
    assert "q2" in contents


def test_only_orphaned_tools():
    """All messages are orphaned tools — should not return out of bounds."""
    msgs = [
        {"role": "tool", "tool_call_id": "x"},
        {"role": "tool", "tool_call_id": "y"},
    ]
    result = find_legal_message_start(msgs)
    # Should return a valid index, not len(msgs)
    assert 0 <= result < len(msgs)


def test_consecutive_orphans():
    """Multiple consecutive orphaned tools."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1"}]},
        {"role": "tool", "tool_call_id": "tc1"},
        {"role": "tool", "tool_call_id": "orphan1"},
        {"role": "tool", "tool_call_id": "orphan2"},
        {"role": "user", "content": "after"},
    ]
    result = find_legal_message_start(msgs)
    # Skip past orphan2 at index 3
    assert result >= 4
    retained = msgs[result:]
    contents = [m.get("content") for m in retained]
    assert "after" in contents
