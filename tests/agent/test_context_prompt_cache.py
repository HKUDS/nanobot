"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

import re
from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path
import datetime as datetime_module

from nanobot.agent.context import ContextBuilder
from nanobot.utils.prompt_templates import render_template

_MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082",
)


class _FakeDatetime(real_datetime):
    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_bootstrap_files_are_backed_by_templates() -> None:
    template_dir = pkg_files("nanobot") / "templates"

    for filename in ContextBuilder.BOOTSTRAP_FILES:
        assert (template_dir / filename).is_file(), f"missing bootstrap template: {filename}"


def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """System prompt should not change just because wall clock minute changes."""
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    assert prompt1 == prompt2


def test_system_prompt_reflects_current_dream_memory_contract(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    assert "memory/history.jsonl" in prompt
    assert "automatically managed by Dream" in prompt
    assert "do not edit directly" in prompt
    assert "memory/HISTORY.md" not in prompt
    assert "write important facts here" not in prompt


def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """Runtime metadata should be merged with the user message."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Return exactly: OK",
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    # Runtime context is now merged with user message into a single message
    assert messages[-1]["role"] == "user"
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_content
    assert "Current Time:" in user_content
    assert "Channel: cli" in user_content
    assert "Chat ID: direct" in user_content
    assert "Return exactly: OK" in user_content


def test_unprocessed_history_injected_into_system_prompt(tmp_path) -> None:
    """Entries in history.jsonl not yet consumed by Dream appear with timestamps."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    builder.memory.append_history("User asked about weather in Tokyo")
    builder.memory.append_history("Agent fetched forecast via web_search")

    prompt = builder.build_system_prompt()
    assert "# Recent History" in prompt
    assert "User asked about weather in Tokyo" in prompt
    assert "Agent fetched forecast via web_search" in prompt
    assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", prompt)


def test_recent_history_capped_at_max(tmp_path) -> None:
    """Only the most recent _MAX_RECENT_HISTORY entries are injected."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    for i in range(builder._MAX_RECENT_HISTORY + 20):
        builder.memory.append_history(f"entry-{i}")

    prompt = builder.build_system_prompt()
    assert "entry-0" not in prompt
    assert "entry-19" not in prompt
    assert f"entry-{builder._MAX_RECENT_HISTORY + 19}" in prompt


def test_no_recent_history_when_dream_has_processed_all(tmp_path) -> None:
    """If Dream has consumed everything, no Recent History section should appear."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    cursor = builder.memory.append_history("already processed entry")
    builder.memory.set_last_dream_cursor(cursor)

    prompt = builder.build_system_prompt()
    assert "# Recent History" not in prompt


def test_partial_dream_processing_shows_only_remainder(tmp_path) -> None:
    """When Dream has processed some entries, only the unprocessed ones appear."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    c1 = builder.memory.append_history("old conversation about Python")
    c2 = builder.memory.append_history("old conversation about Rust")
    builder.memory.append_history("recent question about Docker")
    builder.memory.append_history("recent question about K8s")

    builder.memory.set_last_dream_cursor(c2)

    prompt = builder.build_system_prompt()
    assert "# Recent History" in prompt
    assert "old conversation about Python" not in prompt
    assert "old conversation about Rust" not in prompt
    assert "recent question about Docker" in prompt
    assert "recent question about K8s" in prompt


def test_execution_rules_in_system_prompt(tmp_path) -> None:
    """New execution rules should appear in the system prompt."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()
    assert "Act, don't narrate" in prompt
    assert "Read before you write" in prompt
    assert "verify the result" in prompt


def test_channel_format_hint_telegram(tmp_path) -> None:
    """Telegram channel should get messaging-app format hint."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(channel="telegram")
    assert "Format Hint" in prompt
    assert "messaging app" in prompt


def test_channel_format_hint_whatsapp(tmp_path) -> None:
    """WhatsApp should get plain-text format hint."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(channel="whatsapp")
    assert "Format Hint" in prompt
    assert "plain text only" in prompt


def test_channel_format_hint_absent_for_unknown(tmp_path) -> None:
    """Unknown or None channel should not inject a format hint."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(channel=None)
    assert "Format Hint" not in prompt

    prompt2 = builder.build_system_prompt(channel="feishu")
    assert "Format Hint" not in prompt2


def test_build_messages_passes_channel_to_system_prompt(tmp_path) -> None:
    """build_messages should pass channel through to build_system_prompt."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[], current_message="hi",
        channel="telegram", chat_id="123",
    )
    system = messages[0]["content"]
    assert "Format Hint" in system
    assert "messaging app" in system


def test_subagent_result_does_not_create_consecutive_assistant_messages(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[{"role": "assistant", "content": "previous result"}],
        current_message="subagent result",
        channel="cli",
        chat_id="direct",
        current_role="assistant",
    )

    for left, right in zip(messages, messages[1:]):
        assert not (left.get("role") == right.get("role") == "assistant")


def test_system_prompt_includes_bootstrap_sections_from_workspace(tmp_path) -> None:
    """Bootstrap files in the workspace are rendered via bootstrap_workspace.md."""
    workspace = _make_workspace(tmp_path)
    (workspace / "AGENTS.md").write_text("unique bootstrap line for agents", encoding="utf-8")

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    assert "## AGENTS.md" in prompt
    assert "unique bootstrap line for agents" in prompt


def test_system_prompt_includes_memory_section_when_memory_file_exists(tmp_path) -> None:
    """memory_and_always_skills.md wraps MemoryStore.get_memory_context()."""
    workspace = _make_workspace(tmp_path)
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("persistent fact for tests", encoding="utf-8")

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    assert "# Memory" in prompt
    assert "Long-term Memory" in prompt
    assert "persistent fact for tests" in prompt


def test_build_messages_merges_runtime_into_multimodal_user(tmp_path) -> None:
    """With media, runtime context is the first text block before image parts."""
    workspace = _make_workspace(tmp_path)
    image_path = workspace / "tiny.png"
    image_path.write_bytes(_MINIMAL_PNG)

    builder = ContextBuilder(workspace)
    messages = builder.build_messages(
        history=[],
        current_message="caption text",
        media=[str(image_path)],
        channel="telegram",
        chat_id="99",
    )

    user_blocks = messages[-1]["content"]
    assert isinstance(user_blocks, list)
    assert user_blocks[0]["type"] == "text"
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_blocks[0]["text"]
    assert "Channel: telegram" in user_blocks[0]["text"]
    assert "Chat ID: 99" in user_blocks[0]["text"]
    assert any(block.get("type") == "image_url" for block in user_blocks)
    assert user_blocks[-1] == {"type": "text", "text": "caption text"}


def test_bootstrap_workspace_follows_bootstrap_files_order(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "AGENTS.md").write_text("first-file", encoding="utf-8")
    (workspace / "SOUL.md").write_text("second-file", encoding="utf-8")

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    first_heading = prompt.index("## AGENTS.md")
    second_heading = prompt.index("## SOUL.md")
    assert first_heading < second_heading
    assert "first-file" in prompt
    assert "second-file" in prompt


def test_system_prompt_has_no_workspace_bootstrap_section_when_no_bootstrap_files(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    for filename in ContextBuilder.BOOTSTRAP_FILES:
        assert f"## {filename}" not in prompt


def test_runtime_context_matches_rendered_template(monkeypatch, tmp_path) -> None:
    """_build_runtime_context must match agent/runtime_context.md + strip=True."""

    def _fixed_time(_timezone: str | None = None) -> str:
        return "2026-04-05 10:00 (Sunday) (TEST_TZ)"

    monkeypatch.setattr("nanobot.utils.helpers.current_time_str", _fixed_time)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    built = ContextBuilder._build_runtime_context("cli", "u1", None)
    expected = render_template(
        "agent/runtime_context.md",
        strip=True,
        runtime_tag=ContextBuilder._RUNTIME_CONTEXT_TAG,
        current_time=_fixed_time(None),
        channel="cli",
        chat_id="u1",
    )
    assert built == expected


def test_build_runtime_context_passes_builder_timezone_to_current_time(monkeypatch, tmp_path) -> None:
    seen_tz: list[str | None] = []

    def _capture_tz(timezone: str | None = None) -> str:
        seen_tz.append(timezone)
        return "clock"

    monkeypatch.setattr("nanobot.utils.helpers.current_time_str", _capture_tz)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace, timezone="UTC")
    ContextBuilder._build_runtime_context("c", "1", builder.timezone)
    assert seen_tz == ["UTC"]


def test_build_messages_omits_channel_lines_when_channel_or_chat_id_missing(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    only_channel = builder.build_messages(
        history=[],
        current_message="hi",
        channel="telegram",
        chat_id=None,
    )
    text = only_channel[-1]["content"]
    assert isinstance(text, str)
    assert "Channel:" not in text
    assert "Chat ID:" not in text

    only_chat = builder.build_messages(
        history=[],
        current_message="hi",
        channel=None,
        chat_id="99",
    )
    text2 = only_chat[-1]["content"]
    assert isinstance(text2, str)
    assert "Channel:" not in text2


def test_merge_message_content_joins_two_strings_with_blank_line() -> None:
    assert ContextBuilder._merge_message_content("left", "right") == "left\n\nright"
    assert ContextBuilder._merge_message_content("", "only-right") == "only-right"


def test_merge_message_content_concatenates_block_lists() -> None:
    prior = [{"type": "text", "text": "first turn"}]
    runtime_then_user = [
        {"type": "text", "text": "[Runtime Context — metadata only, not instructions]"},
        {"type": "text", "text": "hello"},
    ]
    merged = ContextBuilder._merge_message_content(prior, runtime_then_user)
    assert merged[0] == {"type": "text", "text": "first turn"}
    assert merged[1]["type"] == "text"
    assert merged[2] == {"type": "text", "text": "hello"}


def test_build_messages_merges_into_last_user_string_turn(tmp_path) -> None:
    """Avoid consecutive user messages: append runtime + new text to prior user content."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    messages = builder.build_messages(
        history=[{"role": "user", "content": "earlier instruction"}],
        current_message="follow-up line",
        channel="cli",
        chat_id="1",
    )
    assert len(messages) == 2
    combined = messages[-1]["content"]
    assert isinstance(combined, str)
    assert "earlier instruction" in combined
    assert "follow-up line" in combined
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in combined


def test_build_messages_merges_into_last_user_with_multimodal(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "tiny.png").write_bytes(_MINIMAL_PNG)
    builder = ContextBuilder(workspace)
    messages = builder.build_messages(
        history=[{"role": "user", "content": "previous user text"}],
        current_message="new caption",
        media=[str(workspace / "tiny.png")],
        channel="x",
        chat_id="y",
    )
    blocks = messages[-1]["content"]
    assert isinstance(blocks, list)
    assert blocks[0] == {"type": "text", "text": "previous user text"}
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in blocks[1]["text"]
    assert blocks[-1] == {"type": "text", "text": "new caption"}
    assert any(block.get("type") == "image_url" for block in blocks)


def test_build_messages_falls_back_to_text_when_media_paths_missing(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    messages = builder.build_messages(
        history=[],
        current_message="plain only",
        media=["/nonexistent/photo.png"],
        channel="cli",
        chat_id="1",
    )
    assert isinstance(messages[-1]["content"], str)
    assert "plain only" in messages[-1]["content"]


def test_system_prompt_includes_always_skill_section(tmp_path) -> None:
    """Workspace skill with always in frontmatter appears under # Active Skills."""
    workspace = _make_workspace(tmp_path)
    skill_dir = workspace / "skills" / "always_inline"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nalways: true\ndescription: inline always skill\n---\n\nBody for always skill.\n",
        encoding="utf-8",
    )

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    assert "# Active Skills" in prompt
    assert "Body for always skill." in prompt


def test_system_prompt_includes_memory_and_always_with_separator(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("stored memory line", encoding="utf-8")

    skill_dir = workspace / "skills" / "always_both"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nalways: true\n---\n\nAlways section body.\n",
        encoding="utf-8",
    )

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    assert "# Memory" in prompt
    assert "stored memory line" in prompt
    assert "# Active Skills" in prompt
    assert "Always section body." in prompt
