"""Test skill enable/disable functionality (issue #1932)."""

import tempfile
from pathlib import Path

from nanobot.agent.skills import SkillsLoader


def test_skill_enabled_by_default():
    """Skills without 'enabled' field should be enabled by default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "default-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: default-skill
description: Default skill
---
# Default
""")

        loader = SkillsLoader(workspace)
        skills = loader.list_skills(filter_unavailable=False)
        skill_names = [s["name"] for s in skills]

        assert "default-skill" in skill_names


def test_skill_can_be_disabled():
    """Skills with 'enabled: false' should not be listed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "disabled-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: disabled-skill
description: Disabled skill
enabled: false
---
# Disabled
""")

        loader = SkillsLoader(workspace)
        skills = loader.list_skills(filter_unavailable=False)
        skill_names = [s["name"] for s in skills]

        assert "disabled-skill" not in skill_names


def test_skill_explicitly_enabled():
    """Skills with 'enabled: true' should be listed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "enabled-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: enabled-skill
description: Enabled skill
enabled: true
---
# Enabled
""")

        loader = SkillsLoader(workspace)
        skills = loader.list_skills(filter_unavailable=False)
        skill_names = [s["name"] for s in skills]

        assert "enabled-skill" in skill_names


def test_skill_disabled_with_no():
    """Skills with 'enabled: no' should not be listed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "disabled-no"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: disabled-no
description: Disabled with no
enabled: no
---
# Disabled No
""")

        loader = SkillsLoader(workspace)
        skills = loader.list_skills(filter_unavailable=False)
        skill_names = [s["name"] for s in skills]

        assert "disabled-no" not in skill_names


def test_disabled_skill_not_in_summary():
    """Disabled skills should not appear in build_skills_summary()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        # Create enabled skill
        s1 = skills_dir / "enabled"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("""---
name: enabled
description: Enabled
---
# Enabled
""")

        # Create disabled skill
        s2 = skills_dir / "disabled"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("""---
name: disabled
description: Disabled
enabled: false
---
# Disabled
""")

        loader = SkillsLoader(workspace)
        summary = loader.build_skills_summary()

        assert "enabled" in summary
        assert "disabled" not in summary


def test_disabled_skill_not_in_always_skills():
    """Disabled skills should not be in get_always_skills() even if marked always=true."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "always-but-disabled"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: always-but-disabled
description: Always but disabled
always: true
enabled: false
---
# Always But Disabled
""")

        loader = SkillsLoader(workspace)
        always_skills = loader.get_always_skills()

        assert "always-but-disabled" not in always_skills


def test_load_skill_works_for_disabled():
    """load_skill() should still work for disabled skills (for re-enabling)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "disabled"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: disabled
description: Disabled
enabled: false
---
# Disabled Content
""")

        loader = SkillsLoader(workspace)
        content = loader.load_skill("disabled")

        assert content is not None
        assert "Disabled Content" in content
