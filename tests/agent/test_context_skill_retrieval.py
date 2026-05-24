"""Tests for skill retrieval integration in ContextBuilder."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import SkillsLoader
from nanobot.config.schema import SkillRetrievalConfig


def _write_skill(base: Path, name: str, *, description: str, body: str = "# Skill\n") -> None:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(["---", f"description: {description}", "---", "", body]),
        encoding="utf-8",
    )


def _make_builder(
    tmp_path: Path,
    *,
    enable: bool = False,
    fallback: bool = True,
    top_k: int = 8,
) -> tuple[ContextBuilder, Path]:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    retrieval = SkillRetrievalConfig(
        enable=enable,
        top_k=top_k,
        fallback_to_full_list=fallback,
        rebuild_on_startup=False,
    )
    builder = ContextBuilder(
        workspace,
        disabled_skills=[],
        skill_retrieval=retrieval,
    )
    builder.skills = SkillsLoader(workspace, builtin_skills_dir=builtin)
    return builder, builtin


def test_retrieval_disabled_matches_full_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_skill(ws_skills, "cron", description="Schedule reminders")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")

    disabled = ContextBuilder(workspace, skill_retrieval=SkillRetrievalConfig(enable=False))
    disabled.skills = SkillsLoader(workspace, builtin_skills_dir=builtin)

    enabled_off = ContextBuilder(
        workspace,
        skill_retrieval=SkillRetrievalConfig(enable=False),
    )
    enabled_off.skills = SkillsLoader(workspace, builtin_skills_dir=builtin)

    prompt_disabled = disabled.build_system_prompt(retrieval_query="cron reminder")
    prompt_off = enabled_off.build_system_prompt(retrieval_query="cron reminder")
    assert prompt_disabled == prompt_off
    assert "**cron**" in prompt_disabled
    assert "**pdf**" in prompt_disabled


def test_retrieval_enabled_limits_skills_section(tmp_path: Path) -> None:
    builder, _builtin = _make_builder(tmp_path, enable=True, top_k=2)
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders and cron jobs")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")
    _write_skill(ws_skills, "github", description="GitHub pull request workflows")

    builder.warm_skill_index()
    prompt = builder.build_system_prompt(retrieval_query="set a cron reminder")

    skills_section = prompt.split("# Skills\n", 1)[1].split("\n\n---")[0]
    skill_lines = [line for line in skills_section.splitlines() if line.startswith("- **")]
    assert len(skill_lines) <= 2
    assert any("cron" in line for line in skill_lines)


def test_retrieval_empty_query_falls_back_to_full_list(tmp_path: Path) -> None:
    builder, _builtin = _make_builder(tmp_path, enable=True)
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")

    builder.warm_skill_index()
    prompt = builder.build_system_prompt(retrieval_query="   ")

    assert "**cron**" in prompt
    assert "**pdf**" in prompt


def test_retrieval_no_hits_and_no_fallback_returns_empty_skills_section(tmp_path: Path) -> None:
    builder, _builtin = _make_builder(tmp_path, enable=True, fallback=False, top_k=2)
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")

    builder.warm_skill_index()
    prompt = builder.build_system_prompt(retrieval_query="quantum entanglement physics")

    assert "# Skills" not in prompt


def test_build_messages_passes_current_message_to_retrieval(tmp_path: Path) -> None:
    builder, _builtin = _make_builder(tmp_path, enable=True, top_k=2)
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders and cron jobs")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")

    builder.warm_skill_index()
    messages = builder.build_messages(
        history=[],
        current_message="please schedule a cron reminder",
        channel="cli",
        chat_id="direct",
    )
    system = messages[0]["content"]
    skills_section = system.split("# Skills\n", 1)[1].split("\n\n---")[0]
    assert "**cron**" in skills_section


def test_build_skills_summary_with_explicit_entries(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    cron_path = ws_skills / "cron" / "SKILL.md"
    cron_path.parent.mkdir(parents=True)
    cron_path.write_text(
        "\n".join(["---", "description: Schedule reminders", "---", "", "# Cron"]),
        encoding="utf-8",
    )
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")

    skills_loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
    summary = skills_loader.build_skills_summary(
        entries=[
            {
                "name": "cron",
                "path": str(cron_path),
                "source": "workspace",
                "description": "Schedule reminders",
                "available": True,
                "missing_requirements": "",
            }
        ]
    )
    assert "cron" in summary
    assert "pdf" not in summary
