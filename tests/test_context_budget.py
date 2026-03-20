"""Tests for AgentLoop._trim_history_for_budget()."""

from nanobot.agent.loop import AgentLoop
from nanobot.utils.helpers import estimate_message_tokens


def _mk_loop(budget: int = 0) -> AgentLoop:
    """Create a minimal AgentLoop for testing trim logic."""
    loop = AgentLoop.__new__(AgentLoop)
    loop.context_budget_tokens = max(budget, 500) if budget > 0 else 0
    return loop


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


# --- Test: budget=0 is a no-op ---

def test_budget_zero_returns_same_list():
    loop = _mk_loop(budget=0)
    msgs = [_system(), _user("old1"), _assistant("old reply"), _user("current")]
    turn_start = 3
    result = loop._trim_history_for_budget(msgs, turn_start, iteration=2)
    assert result is msgs


# --- Test: iteration 1 never trims ---

def test_first_iteration_returns_same_list():
    loop = _mk_loop(budget=500)
    msgs = [_system(), _user("old1"), _assistant("old reply"), _user("current")]
    turn_start = 3
    result = loop._trim_history_for_budget(msgs, turn_start, iteration=1)
    assert result is msgs


# --- Test: no old history is a no-op ---

def test_no_old_history_returns_unchanged():
    loop = _mk_loop(budget=500)
    msgs = [_system(), _user("current")]
    result = loop._trim_history_for_budget(msgs, turn_start_index=1, iteration=2)
    assert result is msgs


# --- Test: history under budget is a no-op ---

def test_history_under_budget_returns_unchanged():
    loop = _mk_loop(budget=50000)
    msgs = [_system(), _user("old msg"), _assistant("reply"), _user("current")]
    result = loop._trim_history_for_budget(msgs, turn_start_index=3, iteration=2)
    assert result is msgs


# --- Test: basic trim removes oldest messages ---

def test_basic_trim_removes_oldest():
    loop = _mk_loop(budget=500)
    old_msgs = []
    for i in range(40):
        old_msgs.append(_user(f"old message number {i} with some padding text to inflate tokens"))
        old_msgs.append(_assistant(f"reply to message {i} with extra content for token count"))
    current_user = _user("current task: do something")
    current_tc = _assistant(None, [_tool_call("tc1")])
    current_result = _tool_result("tc1", "done")

    msgs = [_system()] + old_msgs + [current_user, current_tc, current_result]
    turn_start = 1 + len(old_msgs)

    result = loop._trim_history_for_budget(msgs, turn_start, iteration=2)

    assert result[-3:] == [current_user, current_tc, current_result]
    assert result[0] == msgs[0]
    trimmed_history = result[1:-3]
    assert len(trimmed_history) < len(old_msgs)
    trimmed_tokens = sum(estimate_message_tokens(m) for m in trimmed_history)
    assert trimmed_tokens <= loop.context_budget_tokens


# --- Test: complete trim when budget very low ---

def test_extreme_trim_keeps_system_and_current_turn():
    loop = _mk_loop(budget=500)
    old_msgs = [_user("x" * 2000), _assistant("y" * 2000)]
    current = _user("current")
    msgs = [_system()] + old_msgs + [current]
    turn_start = 3

    result = loop._trim_history_for_budget(msgs, turn_start, iteration=2)

    assert result[0] == msgs[0]
    assert result[-1] == current
    assert len(result) <= len(msgs)


# --- Test: tool-call boundary integrity ---

def test_trim_respects_tool_call_boundaries():
    loop = _mk_loop(budget=500)
    old = [
        _user("padding " * 200),
        _assistant(None, [_tool_call("old_tc1")]),
        _tool_result("old_tc1", "short"),
        _user("recent msg"),
        _assistant("recent reply"),
    ]
    current = _user("current")
    msgs = [_system()] + old + [current]
    turn_start = 1 + len(old)

    result = loop._trim_history_for_budget(msgs, turn_start, iteration=2)

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


# --- Test: budget floor clamps small values ---

def test_budget_floor_clamps_to_500():
    loop = _mk_loop(budget=50)
    assert loop.context_budget_tokens == 500


def test_budget_zero_stays_zero():
    loop = _mk_loop(budget=0)
    assert loop.context_budget_tokens == 0


# --- Test: original messages list is not mutated ---

def test_original_messages_not_mutated():
    loop = _mk_loop(budget=500)
    old = [_user("x" * 2000), _assistant("y" * 2000)]
    current = _user("current")
    msgs = [_system()] + old + [current]
    original_len = len(msgs)
    turn_start = 3

    _ = loop._trim_history_for_budget(msgs, turn_start, iteration=2)

    assert len(msgs) == original_len


# --- Test: integration — verify wiring in _run_agent_loop context ---

def test_trim_called_with_correct_turn_start():
    """Simulate what _run_agent_loop does: initial messages, then appended tool results."""
    loop = _mk_loop(budget=500)

    history = [_user("old " * 200), _assistant("old reply " * 200)]
    initial = [_system()] + history + [_user("do something")]
    turn_start = len(initial) - 1

    result1 = loop._trim_history_for_budget(initial, turn_start, iteration=1)
    assert result1 is initial

    messages = list(initial)
    messages.append(_assistant(None, [_tool_call("tc1")]))
    messages.append(_tool_result("tc1", "result data"))

    result2 = loop._trim_history_for_budget(messages, turn_start, iteration=2)
    assert result2 is not messages
    assert result2[0] == messages[0]
    assert result2[-3]["role"] == "user"
    assert result2[-2].get("tool_calls") is not None
    assert result2[-1]["role"] == "tool"
    assert len(result2) < len(messages)
