"""Tests for :class:`~nanobot.agent.tools.skills.ManageSkillTool`."""

from __future__ import annotations

import pytest

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.skills import ManageSkillTool


def _valid_skill_md(name: str, desc: str = "A test skill.") -> str:
    return "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: {desc}",
            "---",
            "",
            "# Body",
        ]
    )


@pytest.mark.asyncio
async def test_manage_skill_list_and_get(tmp_path) -> None:
    ws = tmp_path / "ws"
    skills = ws / "skills"
    skills.mkdir(parents=True)
    (skills / "alpha").mkdir()
    (skills / "alpha" / "SKILL.md").write_text(_valid_skill_md("alpha"), encoding="utf-8")
    builtin = tmp_path / "bi"
    builtin.mkdir()
    (builtin / "beta").mkdir()
    (builtin / "beta" / "SKILL.md").write_text(_valid_skill_md("beta"), encoding="utf-8")

    loader = SkillsLoader(ws, builtin_skills_dir=builtin)
    tool = ManageSkillTool(loader=loader)

    listed = await tool.execute(operation="list", include_unavailable=True)
    assert "alpha" in listed and "beta" in listed

    got = await tool.execute(operation="get", name="alpha")
    assert "source" in got and "workspace" in got
    assert "# Body" in got

    missing = await tool.execute(operation="get", name="nope")
    assert missing.startswith("Error:")


@pytest.mark.asyncio
async def test_manage_skill_create_update_delete(tmp_path) -> None:
    ws = tmp_path / "ws"
    builtin = tmp_path / "bi"
    builtin.mkdir()
    loader = SkillsLoader(ws, builtin_skills_dir=builtin)
    tool = ManageSkillTool(loader=loader)

    out = await tool.execute(
        operation="create",
        name="new-skill",
        content=_valid_skill_md("new-skill"),
    )
    assert "Created" in out
    assert (ws / "skills" / "new-skill" / "SKILL.md").is_file()

    out = await tool.execute(
        operation="update",
        name="new-skill",
        content=_valid_skill_md("new-skill", desc="v2"),
    )
    assert "Updated" in out
    assert "v2" in (ws / "skills" / "new-skill" / "SKILL.md").read_text(encoding="utf-8")

    out = await tool.execute(operation="delete", name="new-skill")
    assert "Deleted" in out
    assert not (ws / "skills" / "new-skill").exists()


@pytest.mark.asyncio
async def test_manage_skill_update_builtin_errors(tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws / "skills").mkdir(parents=True)
    builtin = tmp_path / "bi"
    (builtin / "builtin-s").mkdir(parents=True)
    (builtin / "builtin-s" / "SKILL.md").write_text(_valid_skill_md("builtin-s"), encoding="utf-8")
    loader = SkillsLoader(ws, builtin_skills_dir=builtin)
    tool = ManageSkillTool(loader=loader)

    out = await tool.execute(
        operation="update",
        name="builtin-s",
        content=_valid_skill_md("builtin-s", desc="hack"),
    )
    assert "Error:" in out and "read-only" in out.lower()
