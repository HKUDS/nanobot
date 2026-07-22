from nanobot.agent.context_governance import ContextGovernor


def _assistant_tool_call(call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": "exec", "arguments": "{}"},
        }],
    }


def test_drop_orphan_tool_results_drops_missing_tool_call_id() -> None:
    messages = [
        _assistant_tool_call("call_1"),
        {"role": "tool", "name": "exec", "content": "missing id"},
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "ok"},
    ]

    result = ContextGovernor.drop_orphan_tool_results(messages)

    assert [m.get("tool_call_id") for m in result if m.get("role") == "tool"] == ["call_1"]


def test_drop_orphan_tool_results_drops_duplicate_tool_result() -> None:
    messages = [
        _assistant_tool_call("call_1"),
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "first"},
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "duplicate"},
    ]

    result = ContextGovernor.drop_orphan_tool_results(messages)

    tool_results = [m for m in result if m.get("role") == "tool"]
    assert len(tool_results) == 1
    assert tool_results[0]["content"] == "first"
