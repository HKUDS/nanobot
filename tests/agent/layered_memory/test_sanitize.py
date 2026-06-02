"""Tests for L0 message sanitization (LM2-A)."""

from nanobot.agent.layered_memory.sanitize import (
    _RUNTIME_CONTEXT_END,
    _RUNTIME_CONTEXT_TAG,
    sanitize_message,
    sanitize_turn_messages,
)


def test_sanitize_strips_runtime_context_from_user() -> None:
    tag = _RUNTIME_CONTEXT_TAG
    end = _RUNTIME_CONTEXT_END
    raw = (
        "What is layered memory?\n\n"
        f"{tag}\n[Task canvas]\n```mermaid\ngraph TD\n```\n{end}"
    )
    row = sanitize_message({"role": "user", "content": raw})
    assert row is not None
    assert row.content == "What is layered memory?"
    assert tag not in row.content
    assert "[Task canvas]" not in row.content


def test_sanitize_keeps_real_user_sentence() -> None:
    text = "请帮我分析 nanobot/agent/loop.py 的结构，用中文回答。"
    row = sanitize_message({"role": "user", "content": text})
    assert row is not None
    assert row.content == text


def test_sanitize_compact_persisted_tool_reference() -> None:
    content = (
        "[tool output persisted]\n"
        "Full output saved to: /tmp/out.txt\n"
        "Original size: 50000 chars\n"
        "node_id: call_big\n"
        "Preview:\nline1\nline2\nline3\nline4\n"
        "... (truncated)\n"
    )
    row = sanitize_message(
        {
            "role": "tool",
            "name": "grep",
            "tool_call_id": "call_big",
            "content": content,
        },
    )
    assert row is not None
    assert "node_id: call_big" in row.content
    assert "line4" not in row.content


def test_sanitize_assistant_tool_calls_only() -> None:
    row = sanitize_message(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
    )
    assert row is not None
    assert "read_file" in row.content


def test_sanitize_skips_system_and_empty() -> None:
    assert sanitize_message({"role": "system", "content": "secret"}) is None
    assert sanitize_message({"role": "user", "content": "  "}) is None


def test_sanitize_turn_messages_preserves_order() -> None:
    rows = sanitize_turn_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    assert [r.role for r in rows] == ["user", "assistant"]
