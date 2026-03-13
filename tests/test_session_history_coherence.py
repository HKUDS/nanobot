from nanobot.session.manager import Session


def test_get_history_preserves_tool_metadata() -> None:
    session = Session(key="cli:direct")
    session.add_message("user", "check repo status")
    session.add_message(
        "assistant",
        "",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "exec", "arguments": "{\"command\":\"git status --short\"}"},
            }
        ],
    )
    session.add_message(
        "tool",
        " M README.md",
        tool_call_id="call_1",
        name="exec",
    )
    session.add_message("assistant", "Working tree has local changes.")

    history = session.get_history(max_messages=10)

    assert history[0] == {"role": "user", "content": "check repo status"}
    assert history[1]["tool_calls"][0]["function"]["name"] == "exec"
    assert history[2]["tool_call_id"] == "call_1"
    assert history[2]["name"] == "exec"


def test_get_history_drops_orphan_tool_results_after_truncation() -> None:
    session = Session(key="feishu:test")

    for i in range(4):
        session.add_message("user", f"u{i}")
        session.add_message("assistant", f"a{i}")

    session.add_message(
        "assistant",
        "",
        tool_calls=[
            {
                "id": "call_orphan",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{\"path\":\"x\"}"},
            }
        ],
    )
    session.add_message("tool", "file-content", tool_call_id="call_orphan", name="read_file")
    session.add_message("assistant", "summary after tool")

    session.add_message("user", "new question")
    session.add_message("assistant", "new answer")

    history = session.get_history(max_messages=4)

    assert [m["role"] for m in history] == ["assistant", "user", "assistant"]
    assert history[0]["content"] == "summary after tool"
    assert all(m.get("role") != "tool" for m in history)
