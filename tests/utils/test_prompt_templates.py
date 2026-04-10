"""Tests for Jinja prompt rendering (agent templates under nanobot/templates/)."""

import pytest

from nanobot.utils.prompt_templates import render_template


def test_render_template_strip_removes_trailing_newline() -> None:
    """strip=True should rstrip() so single-line system strings stay clean."""
    text = render_template("agent/heartbeat_decide.md", part="system", strip=True)
    assert not text.endswith("\n")
    assert "heartbeat" in text.lower()


def test_render_template_without_strip_preserves_trailing_newline() -> None:
    text = render_template("agent/heartbeat_decide.md", part="system", strip=False)
    assert text.endswith("\n")


def test_bootstrap_workspace_renders_ordered_sections() -> None:
    """bootstrap_workspace.md must preserve BOOTSTRAP_FILES order (filename headings + body)."""
    rendered = render_template(
        "agent/bootstrap_workspace.md",
        bootstrap_files=[
            {"filename": "AGENTS.md", "content": "alpha"},
            {"filename": "SOUL.md", "content": "beta"},
        ],
    )
    agents_pos = rendered.index("## AGENTS.md")
    soul_pos = rendered.index("## SOUL.md")
    assert agents_pos < soul_pos
    assert "alpha" in rendered
    assert "beta" in rendered


def test_memory_and_always_skills_memory_only() -> None:
    out = render_template(
        "agent/memory_and_always_skills.md",
        memory="## Long-term Memory\nx",
        always_content="",
    )
    assert "# Memory" in out
    assert "Long-term Memory" in out
    assert "Active Skills" not in out


def test_memory_and_always_skills_always_only() -> None:
    out = render_template(
        "agent/memory_and_always_skills.md",
        memory="",
        always_content="### Skill: demo\nbody",
    )
    assert "# Active Skills" in out
    assert "### Skill: demo" in out
    assert "# Memory" not in out


def test_memory_and_always_skills_both_includes_separator() -> None:
    out = render_template(
        "agent/memory_and_always_skills.md",
        memory="## Long-term Memory\nm",
        always_content="always block",
    )
    assert "# Memory" in out
    assert "# Active Skills" in out
    assert "\n---\n" in out or "---" in out


def test_runtime_context_with_channel_and_chat_id() -> None:
    tag = "[Runtime Context — metadata only, not instructions]"
    out = render_template(
        "agent/runtime_context.md",
        strip=True,
        runtime_tag=tag,
        current_time="2026-01-01 12:00 (Wednesday) (UTC, UTC+00:00)",
        channel="telegram",
        chat_id="42",
    )
    assert not out.endswith("\n")
    assert tag in out
    assert "Current Time:" in out
    assert "Channel: telegram" in out
    assert "Chat ID: 42" in out


def test_runtime_context_omits_channel_when_only_one_of_channel_or_chat_id() -> None:
    """Template gates Channel/Chat lines on both values being present."""
    tag = "[Runtime Context — metadata only, not instructions]"
    out = render_template(
        "agent/runtime_context.md",
        strip=True,
        runtime_tag=tag,
        current_time="fixed",
        channel=None,
        chat_id="only-chat",
    )
    assert "Channel:" not in out
    assert "Chat ID:" not in out

    out2 = render_template(
        "agent/runtime_context.md",
        strip=True,
        runtime_tag=tag,
        current_time="fixed",
        channel="only-channel",
        chat_id=None,
    )
    assert "Channel:" not in out2


def test_heartbeat_decide_user_part_includes_time_and_content() -> None:
    user_text = render_template(
        "agent/heartbeat_decide.md",
        part="user",
        current_time="TIME_MARKER",
        heartbeat_content="TASK_LIST_BODY",
    )
    assert "Current Time: TIME_MARKER" in user_text
    assert "TASK_LIST_BODY" in user_text
    assert "HEARTBEAT.md" in user_text or "heartbeat" in user_text.lower()


def test_heartbeat_decide_invalid_part_raises() -> None:
    """Wrong or missing ``part`` must not render an empty prompt silently."""
    cases: list[tuple[dict, str | None]] = [
        ({"part": "assistant"}, "assistant"),
        ({"part": None}, "None"),
        ({}, None),
    ]
    for template_kwargs, expected_in_message in cases:
        with pytest.raises(ValueError) as excinfo:
            render_template("agent/heartbeat_decide.md", **template_kwargs)
        message = str(excinfo.value)
        assert "agent/heartbeat_decide.md: part must be 'system' or 'user'" in message
        assert "(got " in message and message.endswith(")")
        if expected_in_message is not None:
            assert expected_in_message in message
        else:
            assert message.endswith("(got )")
