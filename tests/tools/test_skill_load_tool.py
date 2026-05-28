"""Tests for the skill_load tool."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.skill_load import SkillLoadTool


def _write_skill(
    workspace: Path,
    name: str,
    *,
    metadata_json: dict | None = None,
    body: str = "# Skill\nUse this skill carefully.",
) -> Path:
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True)
    lines = ["---", f"name: {name}", f"description: {name} skill."]
    if metadata_json is not None:
        payload = json.dumps({"nanobot": metadata_json}, separators=(",", ":"))
        lines.append(f"metadata: {payload}")
    lines.extend(["---", "", body])
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def test_skill_load_returns_formatted_skill_content(tmp_path: Path) -> None:
    _write_skill(tmp_path, "alpha", body="# Alpha\nDo alpha work.")
    tool = SkillLoadTool(workspace=tmp_path, skills_loader=SkillsLoader(tmp_path))

    result = await tool.execute(skill_name="alpha")

    assert result.startswith("### Skill: alpha")
    assert "# Alpha" in result
    assert "Do alpha work." in result
    assert "---" not in result


async def test_skill_load_returns_clear_error_for_missing_skill(tmp_path: Path) -> None:
    _write_skill(tmp_path, "alpha")
    tool = SkillLoadTool(workspace=tmp_path, skills_loader=SkillsLoader(tmp_path))

    result = await tool.execute(skill_name="missing")

    assert "Error: skill 'missing' not found" in result
    assert "alpha" in result


async def test_skill_load_rejects_unavailable_skill(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "needs-tool",
        metadata_json={"requires": {"bins": ["definitely_missing_nanobot_test_bin"]}},
    )
    tool = SkillLoadTool(workspace=tmp_path, skills_loader=SkillsLoader(tmp_path))

    result = await tool.execute(skill_name="needs-tool")

    assert result.startswith("Error: skill 'needs-tool' is unavailable")
    assert "definitely_missing_nanobot_test_bin" in result
