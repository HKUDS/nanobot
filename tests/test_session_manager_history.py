from nanobot.session.manager import Session


def test_get_history_drops_orphan_tool_results_when_window_cuts_tool_calls():
    session = Session(key="telegram:test")
    session.messages.append({"role": "user", "content": "old turn"})

    for i in range(20):
        session.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"old_{i}_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                    {"id": f"old_{i}_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
                ],
            }
        )
        session.messages.append({"role": "tool", "tool_call_id": f"old_{i}_a", "name": "x", "content": "ok"})
        session.messages.append({"role": "tool", "tool_call_id": f"old_{i}_b", "name": "y", "content": "ok"})

    session.messages.append({"role": "user", "content": "problem turn"})
    for i in range(25):
        session.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"cur_{i}_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                    {"id": f"cur_{i}_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
                ],
            }
        )
        session.messages.append({"role": "tool", "tool_call_id": f"cur_{i}_a", "name": "x", "content": "ok"})
        session.messages.append({"role": "tool", "tool_call_id": f"cur_{i}_b", "name": "y", "content": "ok"})

    session.messages.append({"role": "user", "content": "new telegram question"})

    history = session.get_history(max_messages=100)
    assistant_ids = {
        tool_call["id"]
        for message in history
        if message.get("role") == "assistant"
        for tool_call in (message.get("tool_calls") or [])
    }
    orphan_tool_ids = [
        message.get("tool_call_id")
        for message in history
        if message.get("role") == "tool" and message.get("tool_call_id") not in assistant_ids
    ]

    assert orphan_tool_ids == []
