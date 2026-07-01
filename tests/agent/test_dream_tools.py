from unittest.mock import AsyncMock

import pytest

from nanobot.agent.memory import _DreamSkillWriteGuard
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config


class _MockWriteFileTool:
    name = "write_file"
    description = "mock write file"
    parameters = {}
    read_only = False
    concurrency_safe = False
    exclusive = False

    def __init__(self) -> None:
        self.execute = AsyncMock(return_value="wrote file")


def test_tool_loader_scope_memory_only_returns_memory_tools():
    loader = ToolLoader()
    registry = ToolRegistry()
    ctx = ToolContext(config=Config().tools, workspace="/tmp")
    loader.load(ctx, registry, scope="memory")

    names = set(registry.tool_names)
    assert "read_file" in names
    assert "edit_file" in names
    assert "write_file" in names
    assert "list_dir" not in names
    assert "exec" not in names
    assert "message" not in names


def test_dream_skill_write_guard_is_skill_creation(tmp_path):
    guard = _DreamSkillWriteGuard(_MockWriteFileTool(), tmp_path / "skills")

    assert guard._is_skill_creation("skills/my-skill/SKILL.md") is True
    assert guard._is_skill_creation("skills/foo/SKILL.md") is True
    assert guard._is_skill_creation("SOUL.md") is False
    assert guard._is_skill_creation("skills/foo/other.md") is False
    assert guard._is_skill_creation("skills/SKILL.md") is False


@pytest.mark.parametrize(
    ("new_name", "existing", "expected"),
    [
        ("my-skill", ["my-skill"], "my-skill"),
        ("deploy", ["deploy-workflow"], "deploy-workflow"),
        ("deploy-workflow", ["deploy"], "deploy"),
        ("unrelated", ["deploy", "test"], None),
        ("github-deploy-tool", ["github-deploy-staging"], "github-deploy-staging"),
        ("new-skill", [], None),
    ],
)
def test_dream_skill_write_guard_skill_name_conflicts(new_name, existing, expected):
    assert _DreamSkillWriteGuard._skill_name_conflicts(new_name, existing) == expected


def test_dream_skill_write_guard_existing_skill_names(tmp_path):
    skills_dir = tmp_path / "skills"
    (skills_dir / "My-Skill").mkdir(parents=True)
    (skills_dir / "My-Skill" / "SKILL.md").write_text("# My Skill", encoding="utf-8")
    (skills_dir / "Other_Skill").mkdir()
    (skills_dir / "Other_Skill" / "SKILL.md").write_text("# Other Skill", encoding="utf-8")
    (skills_dir / "draft").mkdir()
    (skills_dir / "draft" / "notes.md").write_text("not a skill", encoding="utf-8")
    (skills_dir / "SKILL.md").write_text("not a directory", encoding="utf-8")

    assert sorted(_DreamSkillWriteGuard._existing_skill_names(skills_dir)) == [
        "my-skill",
        "other_skill",
    ]


def test_dream_skill_write_guard_existing_skill_names_empty_dir(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    assert _DreamSkillWriteGuard._existing_skill_names(skills_dir) == []


def test_dream_skill_write_guard_existing_skill_names_missing_dir(tmp_path):
    assert _DreamSkillWriteGuard._existing_skill_names(tmp_path / "missing") == []


async def test_dream_skill_write_guard_execute_blocks_duplicate_creation(tmp_path):
    skills_dir = tmp_path / "skills"
    existing_skill_dir = skills_dir / "existing-skill"
    existing_skill_dir.mkdir(parents=True)
    (existing_skill_dir / "SKILL.md").write_text("# Existing Skill", encoding="utf-8")
    inner = _MockWriteFileTool()
    guard = _DreamSkillWriteGuard(inner, skills_dir)

    result = await guard.execute(
        path="skills/existing-skill/SKILL.md",
        content="# Replacement",
    )

    inner.execute.assert_not_called()
    assert "existing-skill" in result
    assert "Do NOT create a new skill" in result

    result = await guard.execute(
        path="skills/new-unique-skill/SKILL.md",
        content="# New Skill",
    )

    inner.execute.assert_called_once_with(
        path="skills/new-unique-skill/SKILL.md",
        content="# New Skill",
    )
    assert result == "wrote file"


async def test_dream_skill_write_guard_execute_passes_non_skill_paths(tmp_path):
    inner = _MockWriteFileTool()
    guard = _DreamSkillWriteGuard(inner, tmp_path / "skills")

    result = await guard.execute(path="SOUL.md", content="updated soul")

    inner.execute.assert_called_once_with(path="SOUL.md", content="updated soul")
    assert result == "wrote file"
