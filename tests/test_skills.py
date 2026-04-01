import tempfile
from pathlib import Path

import pytest

from nanobot.agent.skills import SkillsLoader


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        yield workspace


@pytest.fixture
def temp_builtin_skills():
    """Create a temporary builtin skills directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        builtin = Path(tmpdir)
        yield builtin


@pytest.fixture
def skills_loader(temp_workspace, temp_builtin_skills):
    """Create a SkillsLoader instance with temporary directories."""
    return SkillsLoader(temp_workspace, temp_builtin_skills)


def create_skill(skill_dir: Path, name: str, content: str = "# Test Skill\n\nTest content."):
    """Helper to create a skill directory and SKILL.md file."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")


def test_list_skills_empty(skills_loader):
    """Test listing skills when no skills exist."""
    skills = skills_loader.list_skills()
    assert skills == []


def test_list_skills_workspace_only(skills_loader, temp_workspace):
    """Test listing skills from workspace only."""
    create_skill(temp_workspace / "skills" / "test1", "test1")
    create_skill(temp_workspace / "skills" / "test2", "test2")

    skills = skills_loader.list_skills()
    assert len(skills) == 2
    assert all(s["source"] == "workspace" for s in skills)
    assert {s["name"] for s in skills} == {"test1", "test2"}


def test_list_skills_builtin_only(skills_loader, temp_builtin_skills):
    """Test listing skills from builtin only."""
    create_skill(temp_builtin_skills / "builtin1", "builtin1")
    create_skill(temp_builtin_skills / "builtin2", "builtin2")

    skills = skills_loader.list_skills()
    assert len(skills) == 2
    assert all(s["source"] == "builtin" for s in skills)
    assert {s["name"] for s in skills} == {"builtin1", "builtin2"}


def test_list_skills_both_sources(skills_loader, temp_workspace, temp_builtin_skills):
    """Test listing skills from both workspace and builtin."""
    create_skill(temp_workspace / "skills" / "workspace_skill", "workspace_skill")
    create_skill(temp_builtin_skills / "builtin_skill", "builtin_skill")

    skills = skills_loader.list_skills()
    assert len(skills) == 2
    assert {s["name"] for s in skills} == {"workspace_skill", "builtin_skill"}
    assert next(s for s in skills if s["name"] == "workspace_skill")["source"] == "workspace"
    assert next(s for s in skills if s["name"] == "builtin_skill")["source"] == "builtin"


def test_list_skills_workspace_priority(skills_loader, temp_workspace, temp_builtin_skills):
    """Test that workspace skills take priority over builtin skills."""
    create_skill(temp_workspace / "skills" / "shared", "shared", "# Workspace version")
    create_skill(temp_builtin_skills / "shared", "shared", "# Builtin version")

    skills = skills_loader.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "shared"
    assert skills[0]["source"] == "workspace"
    assert "Workspace version" in skills_loader.load_skill("shared")


def test_list_skills_ignores_non_directories(skills_loader, temp_workspace):
    """Test that non-directory entries are ignored."""
    (temp_workspace / "skills").mkdir(parents=True, exist_ok=True)
    (temp_workspace / "skills" / "file.txt").write_text("not a directory")

    skills = skills_loader.list_skills()
    assert len(skills) == 0


def test_list_skills_ignores_missing_skill_md(skills_loader, temp_workspace):
    """Test that directories without SKILL.md are ignored."""
    (temp_workspace / "skills" / "no_skill_md").mkdir(parents=True, exist_ok=True)
    (temp_workspace / "skills" / "no_skill_md" / "other.txt").write_text("no skill file")

    skills = skills_loader.list_skills()
    assert len(skills) == 0


def test_list_skills_filter_unavailable(skills_loader, temp_workspace):
    """Test filtering skills by requirements."""
    skill_available = "---\ndescription: Available\n---\n# Available"
    skill_unavailable = """---
description: Unavailable
metadata: '{"nanobot": {"requires": {"bins": ["nonexistent_bin"]}}}'
---

# Unavailable"""
    create_skill(temp_workspace / "skills" / "available", "available", skill_available)
    create_skill(temp_workspace / "skills" / "unavailable", "unavailable", skill_unavailable)

    skills = skills_loader.list_skills(filter_unavailable=True)
    assert len(skills) == 1
    assert skills[0]["name"] == "available"

    skills = skills_loader.list_skills(filter_unavailable=False)
    assert len(skills) == 2
    assert {s["name"] for s in skills} == {"available", "unavailable"}


def test_list_skills_nonexistent_builtin_dir(temp_workspace):
    """Test listing skills when builtin_dir doesn't exist."""
    create_skill(temp_workspace / "skills" / "test", "test", "# Test")

    loader = SkillsLoader(temp_workspace, Path("/nonexistent/path"))
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "test"
    assert skills[0]["source"] == "workspace"
