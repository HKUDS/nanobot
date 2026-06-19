"""Tests for subagent announce text shaping on external channel surfaces."""

from nanobot.utils.subagent_channel_display import (
    scrub_subagent_announce_body,
    scrub_subagent_messages_for_channel,
)


def test_scrub_subagent_keeps_header_and_result_only() -> None:
    raw = """[Subagent 'Phase1' failed]

Task: Collect GitHub stats.

Result:
gh CLI missing.

Summarize this naturally for the user. Keep it brief."""

    out = scrub_subagent_announce_body(raw)
    assert out == "[Subagent 'Phase1' failed]\n\ngh CLI missing."
    assert "Task:" not in out
    assert "Summarize" not in out


def test_scrub_subagent_messages_mutates_matching_rows() -> None:
    messages: list[dict] = [
        {"role": "assistant", "content": "hi"},
        {
            "role": "assistant",
            "content": (
                "[Subagent 'x' completed successfully]\n\nTask: t\n\nResult:\nr\n\nSummarize this naturally"
            ),
            "injected_event": "subagent_result",
        },
    ]
    scrub_subagent_messages_for_channel(messages)
    assert messages[0]["content"] == "hi"
    assert "Task:" not in messages[1]["content"]
    assert "[Subagent 'x' completed successfully]" in messages[1]["content"]
    assert "r" in messages[1]["content"]


def test_scrub_normalizes_crlf_before_result_marker() -> None:
    raw = "[Subagent 'z' failed]\r\n\r\nTask: x\r\n\r\nResult:\r\none line\r\n\r\nSummarize this naturally"
    out = scrub_subagent_announce_body(raw)
    assert "Task:" not in out
    assert out.startswith("[Subagent 'z' failed]")
    assert "one line" in out


def test_scrub_truncates_very_long_result() -> None:
    body = "x" * 900
    raw = f"[Subagent 'z' failed]\n\nTask: t\n\nResult:\n{body}\n\nSummarize this naturally"
    out = scrub_subagent_announce_body(raw)
    assert out.endswith("…")
    assert len(out) < len(raw)
    assert body not in out
