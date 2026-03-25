"""IT-10: SkillsLoader discovery with workspace skills.

Verifies that SkillsLoader discovers SKILL.md files in workspace directories
and produces a skills summary. Does not require LLM API key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.context.skills import SkillsLoader

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_skill(workspace: Path, name: str, description: str) -> Path:
    """Create a minimal skill directory with a SKILL.md file."""
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{description}\n",
        encoding="utf-8",
    )
    return skill_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    def test_discovers_single_workspace_skill(self, tmp_path: Path) -> None:
        """A single workspace skill is discovered by list_skills."""
        _create_skill(tmp_path, "my-tool", "A test tool skill")
        loader = SkillsLoader(tmp_path)

        skills = loader.list_skills(filter_unavailable=False)
        names = [s["name"] for s in skills]

        assert "my-tool" in names

    def test_discovers_multiple_workspace_skills(self, tmp_path: Path) -> None:
        """Multiple workspace skills are all discovered."""
        _create_skill(tmp_path, "alpha", "Alpha skill")
        _create_skill(tmp_path, "beta", "Beta skill")
        _create_skill(tmp_path, "gamma", "Gamma skill")
        loader = SkillsLoader(tmp_path)

        skills = loader.list_skills(filter_unavailable=False)
        names = {s["name"] for s in skills}

        assert {"alpha", "beta", "gamma"}.issubset(names)

    def test_workspace_skills_have_correct_source(self, tmp_path: Path) -> None:
        """Workspace skills are tagged with source='workspace'."""
        _create_skill(tmp_path, "ws-skill", "Workspace skill")
        loader = SkillsLoader(tmp_path)

        skills = loader.list_skills(filter_unavailable=False)
        ws_skills = [s for s in skills if s["name"] == "ws-skill"]

        assert len(ws_skills) == 1
        assert ws_skills[0]["source"] == "workspace"


class TestSkillsSummary:
    def test_summary_includes_workspace_skill(self, tmp_path: Path) -> None:
        """build_skills_summary includes discovered workspace skills."""
        _create_skill(tmp_path, "summarize-me", "A skill for summary testing")
        loader = SkillsLoader(tmp_path)

        summary = loader.build_skills_summary()

        assert "summarize-me" in summary
        assert "Other available skills" in summary

    def test_summary_empty_when_no_workspace_skills_and_no_builtins(self, tmp_path: Path) -> None:
        """Summary is non-empty only if skills exist (builtins always present)."""
        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins")

        summary = loader.build_skills_summary()

        # With no builtins and no workspace skills, summary should be empty
        assert summary == ""

    def test_summary_contains_description(self, tmp_path: Path) -> None:
        """Skill descriptions appear in the summary text."""
        _create_skill(tmp_path, "desc-test", "Unique description for verification")
        loader = SkillsLoader(tmp_path)

        summary = loader.build_skills_summary()

        assert "Unique description for verification" in summary
