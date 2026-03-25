"""Tests for progressive skill loading — summary-only for trigger-matched skills."""

from __future__ import annotations

from pathlib import Path

from nanobot.context.skills import SkillsLoader


def _create_skill(
    workspace: Path,
    name: str,
    description: str,
    *,
    always: bool = False,
    triggers: list[str] | None = None,
) -> Path:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if always:
        frontmatter_lines.append("always: true")
    if triggers:
        frontmatter_lines.append("triggers:")
        for t in triggers:
            frontmatter_lines.append(f"  - {t}")
    frontmatter_lines.append("---")
    content = "\n".join(frontmatter_lines) + "\n\n# Full content\n" + "x" * 200
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


def test_matched_skills_highlighted_in_summary(tmp_path: Path) -> None:
    """Matched skills appear with star marker in summary."""
    _create_skill(tmp_path, "obsidian-cli", "Obsidian CLI tool", triggers=["obsidian"])
    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary(matched=["obsidian-cli"])
    assert "★" in summary
    assert "obsidian-cli" in summary
    assert "Matched for this message" in summary


def test_unmatched_skills_in_other_section(tmp_path: Path) -> None:
    """Non-matched skills appear in 'Other available' section."""
    _create_skill(tmp_path, "weather", "Check weather")
    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary(matched=[])
    assert "Other available skills" in summary
    assert "weather" in summary
    assert "★" not in summary


def test_matched_skills_include_path(tmp_path: Path) -> None:
    """Matched skills include SKILL.md path for read_file."""
    _create_skill(tmp_path, "my-skill", "A skill", triggers=["mytest"])
    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary(matched=["my-skill"])
    assert "SKILL.md" in summary
    assert "Path:" in summary


def test_always_skills_excluded_from_summary(tmp_path: Path) -> None:
    """Always-on skills don't appear in summary (already fully injected)."""
    _create_skill(tmp_path, "always-skill", "Always loaded", always=True)
    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary(matched=[])
    assert "always-skill" not in summary


def test_no_matched_no_matched_section(tmp_path: Path) -> None:
    """When matched=[] or None, no 'Matched' section appears."""
    _create_skill(tmp_path, "some-skill", "A skill")
    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary(matched=None)
    assert "Matched for this message" not in summary
    assert "some-skill" in summary


def test_backward_compat_no_matched_param(tmp_path: Path) -> None:
    """Calling build_skills_summary() without matched still works."""
    _create_skill(tmp_path, "compat-skill", "Backward compat")
    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary()
    assert "compat-skill" in summary
