from __future__ import annotations

import datetime as datetime_module
from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.channels.registry import make_reply_format_resolver
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
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    assert prompt1 == prompt2


def test_selected_project_path_follows_shared_cache_prefix(tmp_path) -> None:
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
    from nanobot.utils.helpers import sync_workspace_templates

    workspace = _make_workspace(tmp_path)
    sync_workspace_templates(workspace, silent=True)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()
    assert "clear user request" in prompt
    assert "execution and verification" in prompt
    assert "Ask for confirmation when an irreversible action requires it" in prompt


def test_execution_rules_reach_existing_workspace_soul(tmp_path) -> None:
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


@pytest.mark.parametrize("legacy_workspace", [False, True])
def test_scheduling_contract_reaches_fresh_and_legacy_workspaces(tmp_path, legacy_workspace) -> None:
    from nanobot.utils.helpers import sync_workspace_templates

    workspace = _make_workspace(tmp_path)
    agents_path = workspace / "AGENTS.md"
    legacy_rule = (
        "When the user asks for a recurring/periodic task, update HEARTBEAT.md "
        "instead of creating a one-time cron reminder."
    )
    if legacy_workspace:
        agents_path.write_text(f"# Workspace rules\nReply in Chinese.\n{legacy_rule}\n", encoding="utf-8")
    sync_workspace_templates(workspace, silent=True)
    original = agents_path.read_bytes()
    builder = ContextBuilder(workspace)
    messages = builder.build_messages(history=[], current_message="每天早上8点提醒我喝水")
    system = messages[0]["content"]

    assert "Use `cron` for a specified time or interval, even if it repeats" in system
    assert "Use `HEARTBEAT.md` only for flexible checks" in system
    if legacy_workspace:
        assert "Reply in Chinese." in system
        assert system.index(legacy_rule) < system.index("## Scheduling")
        assert "Do not substitute heartbeat for an explicit schedule" in system
    else:
        assert "## AGENTS.md" not in system
    assert "每天早上8点提醒我喝水" in messages[-1]["content"]
    assert builder.build_messages(history=[], current_message="Check issues when convenient")[0] == messages[0]
    assert agents_path.read_bytes() == original


@pytest.mark.parametrize("include_memory", [True, False])
def test_channel_format_follows_delivery_medium(tmp_path, include_memory) -> None:
    builder = ContextBuilder(_make_workspace(tmp_path), reply_format_for=make_reply_format_resolver())

    def system(channel: str | None) -> str:
        return builder.build_system_prompt(channel=channel, include_memory=include_memory)

    generic = system(None)
    assert system("feishu") == generic
    assert system("sms") == system("whatsapp")
    assert "plain text only" in system("sms")
    formula = r"use LaTeX with `\(...\)` for inline math and `\[...\]` for display math"
    websocket = system("websocket")
    assert websocket.index("## Workspace") < websocket.index(formula) < websocket.index("## External Content")
    assert formula not in generic


@pytest.mark.parametrize("disabled", [False, True])
def test_memory_skill_is_discoverable_and_lazy_only_when_enabled(tmp_path, disabled) -> None:
    builder = ContextBuilder(_make_workspace(tmp_path), disabled_skills=["memory"] if disabled else None)
    system, user = builder.build_messages(history=[], current_message="$memory Find the decision")

    assert "memory/wiki/index.md" in system["content"]
    assert ("**memory**" in system["content"]) is not disabled
    assert "Search Past Events" not in system["content"]
    assert ("Search Past Events" in user["content"]) is not disabled


def test_fresh_workspace_omits_default_prompt_scaffolding(tmp_path) -> None:
    from nanobot.utils.helpers import sync_workspace_templates

    workspace = _make_workspace(tmp_path)
    sync_workspace_templates(workspace, silent=True)

    prompt = ContextBuilder(workspace).build_system_prompt()

    assert "## AGENTS.md" not in prompt
    assert "## USER.md" not in prompt
    assert "8281248569" not in prompt
    assert "(your name)" not in prompt


def test_template_memory_md_is_skipped(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(workspace, silent=True)

    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()

    assert "# Long-term Memory" not in prompt
    assert "This file is automatically updated by nanobot" not in prompt


def test_customized_memory_md_is_injected(tmp_path, monkeypatch) -> None:
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

    assert prompt.count("# Long-term Memory") == 1
    assert "User prefers dark mode" in prompt
    assert calls == 1
