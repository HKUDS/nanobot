"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

import re
from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path
import datetime as datetime_module

from nanobot.agent.context import ContextBuilder


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
    """Execution rules should appear in the system prompt via default SOUL.md."""
    from nanobot.utils.helpers import sync_workspace_templates

    workspace = _make_workspace(tmp_path)
    sync_workspace_templates(workspace, silent=True)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()
    assert "single-step tasks" in prompt
    assert "multi-step tasks" in prompt
    assert "Read before you write" in prompt
    assert "verify the result" in prompt


def test_identity_has_no_behavioral_instructions(tmp_path) -> None:
    """Identity template should not contain behavioral rules or hardcoded name."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    identity = builder._get_identity(channel=None)
    assert "You are nanobot" not in identity
    assert "Act, don't narrate" not in identity
    assert "Execution Rules" not in identity


def test_default_soul_template_contains_execution_rules() -> None:
    """Default SOUL.md template must contain execution rules with act/plan layering."""
    soul = (pkg_files("nanobot") / "templates" / "SOUL.md").read_text(encoding="utf-8")
    assert "## Execution Rules" in soul
    assert "single-step tasks" in soul
    assert "multi-step tasks" in soul


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


def test_always_skills_excluded_from_skills_index(tmp_path) -> None:
    """Always skills should appear in Active Skills but NOT in the skills index."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    # memory skill should be in Active Skills section
    assert "# Active Skills" in prompt
    assert "### Skill: memory" in prompt

    # memory skill should NOT appear in the skills index
    skills_section = prompt.split("# Skills\n", 1)
    if len(skills_section) > 1:
        index_text = skills_section[1].split("\n\n---")[0]
        assert "**memory**" not in index_text


def test_template_memory_md_is_skipped(tmp_path) -> None:
    """MEMORY.md matching the bundled template should not inject the Memory section."""
    workspace = _make_workspace(tmp_path)
    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(workspace, silent=True)

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    # The "# Memory\n\n## Long-term Memory" block is produced only by
    # build_system_prompt() when MEMORY.md is injected.  The memory skill
    # also contains "# Memory" but is followed by "## Structure", not
    # "## Long-term Memory".
    assert "# Memory\n\n## Long-term Memory" not in prompt
    assert "This file is automatically updated by nanobot" not in prompt


def test_customized_memory_md_is_injected(tmp_path) -> None:
    """A Dream-populated MEMORY.md should be injected normally."""
    workspace = _make_workspace(tmp_path)
    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(workspace, silent=True)

    (workspace / "memory" / "MEMORY.md").write_text(
        "# Long-term Memory\n\nUser prefers dark mode.\n", encoding="utf-8"
    )

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    assert "# Memory\n\n## Long-term Memory" in prompt
    assert "User prefers dark mode" in prompt
