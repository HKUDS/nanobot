"""Tests for skill loading — flat summary + load_skill tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.context.skills import SkillsLoader
from nanobot.tools.builtin.skills import LoadSkillTool


def _create_skill(
    workspace: Path,
    name: str,
    description: str,
    *,
    always: bool = False,
) -> Path:
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter_lines = ["---", f"name: {name}", f"description: {description}"]
    if always:
        frontmatter_lines.append("always: true")
    frontmatter_lines.append("---")
    content = "\n".join(frontmatter_lines) + "\n\n# Full content\nInstructions here."
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


def test_summary_is_flat_list(tmp_path: Path) -> None:
    """Skills summary is a flat list with no matched/unmatched sections."""
    _create_skill(tmp_path, "weather", "Check weather")
    _create_skill(tmp_path, "github", "GitHub integration")
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary()

    assert "weather" in summary
    assert "github" in summary
    assert "Matched for this message" not in summary
    assert "Other available" not in summary
    assert "★" not in summary
    assert "Path:" not in summary


def test_always_skills_excluded_from_summary(tmp_path: Path) -> None:
    _create_skill(tmp_path, "always-skill", "Always loaded", always=True)
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary()

    assert "always-skill" not in summary


def test_summary_empty_when_no_skills(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins")

    summary = loader.build_skills_summary()

    assert summary == ""


@pytest.mark.asyncio
async def test_load_skill_tool_returns_content(tmp_path: Path) -> None:
    _create_skill(tmp_path, "test-skill", "A test skill")
    loader = SkillsLoader(tmp_path)
    tool = LoadSkillTool(skills_loader=loader)

    result = await tool.execute(name="test-skill")

    assert result.success
    assert "Full content" in result.output
    assert "Instructions here" in result.output
    # Frontmatter should be stripped
    assert "---" not in result.output


@pytest.mark.asyncio
async def test_load_skill_tool_not_found(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins")
    tool = LoadSkillTool(skills_loader=loader)

    result = await tool.execute(name="nonexistent")

    assert not result.success
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_load_skill_strips_frontmatter(tmp_path: Path) -> None:
    _create_skill(tmp_path, "fm-skill", "Has frontmatter")
    loader = SkillsLoader(tmp_path)
    tool = LoadSkillTool(skills_loader=loader)

    result = await tool.execute(name="fm-skill")

    assert result.success
    assert "name: fm-skill" not in result.output  # frontmatter stripped
    assert "Full content" in result.output
