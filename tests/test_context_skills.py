from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import SkillsLoader


def _write_skill(workspace: Path, name: str, body: str, *, always: bool = False) -> None:
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = "---\n"
    if always:
        frontmatter += "always: true\n"
    frontmatter += "---\n"
    (skill_dir / "SKILL.md").write_text(f"{frontmatter}\n{body}\n", encoding="utf-8")


def test_build_system_prompt_includes_selected_and_always_skills(tmp_path: Path):
    _write_skill(tmp_path, "always-skill", "Always skill body", always=True)
    _write_skill(tmp_path, "selected-skill", "Selected skill body")
    _write_skill(tmp_path, "other-skill", "Other skill body")
    empty_builtin_dir = tmp_path / "builtin"
    empty_builtin_dir.mkdir()

    builder = ContextBuilder(tmp_path)
    builder.skills = SkillsLoader(tmp_path, builtin_skills_dir=empty_builtin_dir)

    prompt = builder.build_system_prompt(
        ["selected-skill", "always-skill", "selected-skill", "missing-skill"]
    )

    assert "# Active Skills" in prompt
    assert "### Skill: always-skill" in prompt
    assert "### Skill: selected-skill" in prompt
    assert prompt.count("### Skill: always-skill") == 1
    assert prompt.count("### Skill: selected-skill") == 1
    assert "Always skill body" in prompt
    assert "Selected skill body" in prompt
    assert "Other skill body" not in prompt

