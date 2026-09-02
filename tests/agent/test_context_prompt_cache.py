"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

import datetime as datetime_module
from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.runtime_context import RuntimeContextBlock


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


def test_selected_project_path_follows_shared_cache_prefix(tmp_path) -> None:
    """Project paths must not invalidate the stable identity and tool contract prefix."""
    agent_home = tmp_path / "agent-home"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    agent_home.mkdir()
    project_a.mkdir()
    project_b.mkdir()
    builder = ContextBuilder(agent_home)

    prompt_a = builder.build_system_prompt(workspace=project_a)
    prompt_b = builder.build_system_prompt(workspace=project_b)
    marker = "# Current Project"
    prefix_a = prompt_a[: prompt_a.index(marker)]
    prefix_b = prompt_b[: prompt_b.index(marker)]

    assert prefix_a == prefix_b
    assert "# Tool Usage Notes" in prefix_a
    assert str(project_a.resolve()) not in prefix_a
    assert str(project_b.resolve()) not in prefix_b
    assert prompt_a == builder.build_system_prompt(workspace=project_a)


def test_system_prompt_reflects_current_dream_memory_contract(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    assert "memory/history.jsonl" in prompt
    assert "automatically managed by Dream" in prompt
    assert "do not edit directly" in prompt
    assert "memory/HISTORY.md" not in prompt
    assert "write important facts here" not in prompt


def test_provider_context_appended_after_user_content(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="hello world",
        channel="cli",
        runtime_context_blocks=[
            RuntimeContextBlock(source="test", content="provider context"),
        ],
    )

    content = messages[-1]["content"]
    user_pos = content.find("hello world")
    context_pos = content.find("provider context")
    assert user_pos < context_pos, "user content must precede provider context"


def test_execution_rules_in_system_prompt(tmp_path) -> None:
    """Execution rules should appear in the system prompt via the default templates."""
    from nanobot.utils.helpers import sync_workspace_templates

    workspace = _make_workspace(tmp_path)
    sync_workspace_templates(workspace, silent=True)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()
    assert "clear user request" in prompt
    assert "multi-step tasks" in prompt
    assert "read-only discovery before writes" in prompt
    assert "verify the result" in prompt


def test_execution_rules_reach_existing_workspace_soul(tmp_path) -> None:
    """An untouched legacy SOUL is upgraded in memory without overwriting the file."""
    workspace = _make_workspace(tmp_path)
    legacy_soul = (
        pkg_files("nanobot") / "templates" / "legacy" / "SOUL.md"
    ).read_text(encoding="utf-8")
    legacy_rule = "For multi-step tasks, outline the plan first and wait for user confirmation."
    soul_path = workspace / "SOUL.md"
    soul_path.write_text(legacy_soul, encoding="utf-8")
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()
    current_rule = "Treat a clear user request as authorization"

    assert legacy_rule not in prompt
    assert current_rule in prompt
    assert soul_path.read_text(encoding="utf-8") == legacy_soul


def test_identity_has_no_behavioral_instructions(tmp_path) -> None:
    """Identity template should not contain behavioral rules or hardcoded name."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    identity = builder._get_identity(channel=None)
    assert "You are nanobot" not in identity
    assert "Act, don't narrate" not in identity
    assert "Execution Rules" not in identity


def test_system_prompt_does_not_warn_about_message_time_markers(tmp_path) -> None:
    """Parroting is prevented by not annotating assistant turns in history;
    no prompt-level warning about ``[Message Time: ...]`` is needed."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    assert "Message Time" not in prompt


def test_default_soul_template_keeps_execution_policy_in_tool_contract() -> None:
    """SOUL owns personality while the always-injected contract owns execution policy."""
    soul = (pkg_files("nanobot") / "templates" / "SOUL.md").read_text(encoding="utf-8")
    contract = (
        pkg_files("nanobot") / "templates" / "agent" / "tool_contract.md"
    ).read_text(encoding="utf-8")

    assert "## Execution Rules" not in soul
    assert "clear user request" not in soul
    assert "clear user request" in contract
    assert "multi-step tasks" in contract
    assert "irreversible action needs confirmation" in contract


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
        channel="telegram",
    )
    system = messages[0]["content"]
    assert "Format Hint" in system
    assert "messaging app" in system


def test_system_prompt_keeps_message_tool_out_of_current_chat_replies(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(channel="slack")

    assert "Do not use the 'message' tool for normal replies in the current chat" in prompt
    assert "When 'generate_image' creates images" in prompt
    assert "call 'message' with the artifact paths in the 'media' parameter" in prompt
    assert "Wait for the tool results, then answer once" in prompt


def test_memory_skill_is_lazy_loaded_from_skills_index(tmp_path) -> None:
    """Memory search guidance should be discoverable without loading its full body."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    assert "### Skill: memory" not in prompt
    assert "**memory**" in prompt
    assert "Search Past Events" not in prompt
    assert "Examples (replace `keyword`)" not in prompt


def test_fresh_workspace_omits_default_prompt_scaffolding(tmp_path) -> None:
    from nanobot.utils.helpers import sync_workspace_templates

    workspace = _make_workspace(tmp_path)
    sync_workspace_templates(workspace, silent=True)

    prompt = ContextBuilder(workspace).build_system_prompt()

    assert "## AGENTS.md" not in prompt
    assert "## USER.md" not in prompt
    assert "8281248569" not in prompt
    assert "(your name)" not in prompt
    assert "apt/brew" not in prompt
    assert prompt.count("Do not use the 'message' tool for normal replies") == 1


def test_template_memory_md_is_skipped(tmp_path) -> None:
    """MEMORY.md matching the bundled template should not inject the Memory section."""
    workspace = _make_workspace(tmp_path)
    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(workspace, silent=True)

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    # This block is produced only when populated long-term memory is injected.
    assert "# Memory\n\n## Long-term Memory" not in prompt
    assert "This file is automatically updated by nanobot" not in prompt


def test_customized_memory_md_is_injected(tmp_path, monkeypatch) -> None:
    """A Dream-populated MEMORY.md should be injected normally."""
    workspace = _make_workspace(tmp_path)
    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(workspace, silent=True)

    (workspace / "memory" / "MEMORY.md").write_text(
        "# Long-term Memory\n\nUser prefers dark mode.\n", encoding="utf-8"
    )

    builder = ContextBuilder(workspace)
    read_memory = builder.memory.read_memory
    calls = 0

    def tracked_read_memory() -> str:
        nonlocal calls
        calls += 1
        return read_memory()

    monkeypatch.setattr(builder.memory, "read_memory", tracked_read_memory)
    prompt = builder.build_system_prompt()

    assert "# Memory\n\n## Long-term Memory" in prompt
    assert "User prefers dark mode" in prompt
    assert calls == 1
