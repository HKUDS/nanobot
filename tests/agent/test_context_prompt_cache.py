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
