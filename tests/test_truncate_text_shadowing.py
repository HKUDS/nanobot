from types import SimpleNamespace


def test_sanitize_persisted_blocks_preserves_tool_text() -> None:
    from nanobot.agent.loop import AgentLoop

    dummy = SimpleNamespace()
    content = [{"type": "text", "text": "0123456789"}]

    out = AgentLoop._sanitize_persisted_blocks(dummy, content)
    assert out == content

