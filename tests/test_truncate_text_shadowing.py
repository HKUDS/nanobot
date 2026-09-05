from types import SimpleNamespace


def test_sanitize_persisted_blocks_truncates_text() -> None:
    from nanobot.agent.loop import AgentLoop

    dummy = SimpleNamespace(max_tool_result_chars=5)
    content = [{"type": "text", "text": "0123456789"}]

    out = AgentLoop._sanitize_persisted_blocks(dummy, content, should_truncate_text=True)
    assert isinstance(out, list)
    assert out and out[0]["type"] == "text"
    assert isinstance(out[0]["text"], str)
    assert out[0]["text"] != content[0]["text"]

