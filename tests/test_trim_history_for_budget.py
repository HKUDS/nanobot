"""Direct unit tests for trim_history_for_budget() helper."""

import pytest
from nanobot.session.manager import Session
from nanobot.utils.helpers import estimate_message_tokens, trim_history_for_budget


def _msg(role: str, content: str, **kw) -> dict:
    return {"role": role, "content": content, **kw}


def _system(content: str = "You are a bot.") -> dict:
    return _msg("system", content)


def _user(content: str) -> dict:
    return _msg("user", content)


def _assistant(content: str | None = None, tool_calls: list | None = None) -> dict:
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tool_call(tc_id: str, name: str = "exec", args: str = "{}") -> dict:
    return {"id": tc_id, "type": "function", "function": {"name": name, "arguments": args}}


def _tool_result(tc_id: str, content: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "name": "exec", "content": content}


# --- Early-exit cases ---

def test_budget_zero_returns_same_list():
    msgs = [_system(), _user("old1"), _assistant("old reply"), _user("current")]
    result = trim_history_for_budget(msgs, turn_start_index=3, iteration=2, context_budget_tokens=0, find_legal_start=Session._find_legal_start)
    assert result is msgs


def test_iteration_one_never_trims():
    msgs = [_system(), _user("old1"), _assistant("old reply"), _user("current")]
    result = trim_history_for_budget(msgs, turn_start_index=3, iteration=1, context_budget_tokens=1000, find_legal_start=Session._find_legal_start)
    assert result is msgs


def test_turn_start_at_one_returns_same():
    """turn_start_index=1 means no old history before the current turn."""
    msgs = [_system(), _user("current")]
    result = trim_history_for_budget(msgs, turn_start_index=1, iteration=2, context_budget_tokens=0, find_legal_start=Session._find_legal_start)
    assert result is msgs


def test_history_under_budget_returns_unchanged():
    msgs = [_system(), _user("short msg"), _assistant("short reply"), _user("current")]
    result = trim_history_for_budget(msgs, turn_start_index=3, iteration=2, context_budget_tokens=50000, find_legal_start=Session._find_legal_start)
    assert result is msgs


# --- Trimming cases ---

def test_trim_removes_oldest_messages():
    old_msgs = []
    for i in range(40):
        old_msgs.append(_user(f"old message number {i} padding extra text here"))
        old_msgs.append(_assistant(f"reply to message {i} with more padding"))

    current_user = _user("current task")
    current_tc = _assistant(None, [_tool_call("tc1")])
    current_result = _tool_result("tc1", "done")

    msgs = [_system()] + old_msgs + [current_user, current_tc, current_result]
    turn_start = 1 + len(old_msgs)

    result = trim_history_for_budget(msgs, turn_start, iteration=2, context_budget_tokens=500, find_legal_start=Session._find_legal_start)

    # System and current turn preserved
    assert result[0] == msgs[0]
    assert result[-3:] == [current_user, current_tc, current_result]
    # Old history trimmed
    trimmed_history = result[1:-3]
    assert len(trimmed_history) < len(old_msgs)
    # Token budget respected
    trimmed_tokens = sum(estimate_message_tokens(m) for m in trimmed_history)
    assert trimmed_tokens <= 500


def test_trim_preserves_tool_call_boundary():
    """Trimming must not leave orphaned tool results."""
    old = [
        _user("padding " * 200),
        _assistant(None, [_tool_call("old_tc1")]),
        _tool_result("old_tc1", "short result"),
        _user("recent msg"),
        _assistant("recent reply"),
    ]
    current = _user("current")
    msgs = [_system()] + old + [current]
    turn_start = 1 + len(old)

    result = trim_history_for_budget(msgs, turn_start, iteration=2, context_budget_tokens=500, find_legal_start=Session._find_legal_start)

    # Check no orphaned tool results
    trimmed_history = result[1:-1]
    declared_ids = set()
    for m in trimmed_history:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                declared_ids.add(tc["id"])
    for m in trimmed_history:
        if m.get("role") == "tool":
            tc_id = m.get("tool_call_id")
            assert tc_id in declared_ids, f"Orphan tool result: {tc_id}"


def test_extreme_trim_keeps_system_and_current_turn():
    """When budget is tiny, only system and current turn remain."""
    old = [_user("x" * 2000), _assistant("y" * 2000)]
    current = _user("current")
    msgs = [_system()] + old + [current]

    result = trim_history_for_budget(msgs, turn_start_index=3, iteration=2, context_budget_tokens=500, find_legal_start=Session._find_legal_start)

    assert result[0] == msgs[0]  # system
    assert result[-1] == current  # current turn
    assert len(result) <= len(msgs)


def test_original_messages_not_mutated():
    old = [_user("x" * 2000), _assistant("y" * 2000)]
    current = _user("current")
    msgs = [_system()] + old + [current]
    original_len = len(msgs)

    _ = trim_history_for_budget(msgs, turn_start_index=3, iteration=2, context_budget_tokens=500, find_legal_start=Session._find_legal_start)

    assert len(msgs) == original_len


def test_current_turn_never_trimmed():
    """All messages at or after turn_start_index must be preserved verbatim."""
    old = [_user("old"), _assistant("reply")]
    current_turn = [
        _user("current user message"),
        _assistant(None, [_tool_call("tc1")]),
        _tool_result("tc1", "result"),
    ]
    msgs = [_system()] + old + current_turn
    turn_start = 1 + len(old)

    result = trim_history_for_budget(msgs, turn_start, iteration=2, context_budget_tokens=1, find_legal_start=Session._find_legal_start)

    assert result[-len(current_turn):] == current_turn


def test_iteration_two_first_trim():
    """iteration=2 is the first iteration where trimming kicks in."""
    old = [_user("x" * 2000), _assistant("y" * 2000)]
    msgs = [_system()] + old + [_user("current")]
    turn_start = 3

    # iteration=1: no trim
    r1 = trim_history_for_budget(msgs, turn_start, iteration=1, context_budget_tokens=0, find_legal_start=Session._find_legal_start)
    assert r1 is msgs

    # iteration=2 with budget=0: no trim (budget is 0)
    r2 = trim_history_for_budget(msgs, turn_start, iteration=2, context_budget_tokens=0, find_legal_start=Session._find_legal_start)
    assert r2 is msgs

    # iteration=2 with positive budget: trim occurs (2000-char msgs ~= 500+ tokens each)
    r3 = trim_history_for_budget(msgs, turn_start, iteration=2, context_budget_tokens=500, find_legal_start=Session._find_legal_start)
    assert r3 is not msgs
