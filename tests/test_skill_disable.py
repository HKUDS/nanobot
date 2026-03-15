"""Test skill enable/disable functionality via hook storage."""

import tempfile
from pathlib import Path

from nanobot.agent.hooks.storage import HookStorage
from nanobot.agent.hooks import HookEvent, SkillsEnabledFilter
from nanobot.agent.skills import SkillsLoader


def test_skill_enabled_by_default():
    """Skills should be enabled by default (not in hook storage)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "default-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: default-skill\ndescription: Default\n---\n# Default\n")

        storage = HookStorage(workspace)
        assert not storage.is_skill_disabled("default-skill")


def test_disable_via_hook_storage():
    """Disabling a skill adds it to hook storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: Test\n---\n# My Skill\n")

        storage = HookStorage(workspace)
        storage.set_skill_enabled("my-skill", False)
        assert storage.is_skill_disabled("my-skill")

        # Skill file should NOT be modified
        content = (skill_dir / "SKILL.md").read_text()
        assert "enabled: false" not in content


def test_enable_via_hook_storage():
    """Enabling a skill removes it from hook storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "skills").mkdir()

        storage = HookStorage(workspace)
        storage.set_skill_enabled("my-skill", False)
        assert storage.is_skill_disabled("my-skill")

        storage.set_skill_enabled("my-skill", True)
        assert not storage.is_skill_disabled("my-skill")


def test_filter_removes_disabled_skill():
    """SkillsEnabledFilter should remove disabled skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test-skill\n---\n# Test")

        storage = HookStorage(workspace)
        storage.set_skill_enabled("test-skill", False)

        f = SkillsEnabledFilter(workspace)
        skills = [{"name": "test-skill", "path": str(skill_dir / "SKILL.md"), "source": "workspace"}]
        result = f.on_event(HookEvent.PRE_BUILD_CONTEXT, {"type": "skills", "data": skills})
        assert len(result.modified_data) == 0


def test_filter_keeps_enabled_skill():
    """SkillsEnabledFilter should keep enabled skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test-skill\n---\n# Test")

        f = SkillsEnabledFilter(workspace)
        skills = [{"name": "test-skill", "path": str(skill_dir / "SKILL.md"), "source": "workspace"}]
        result = f.on_event(HookEvent.PRE_BUILD_CONTEXT, {"type": "skills", "data": skills})
        assert len(result.modified_data) == 1


def test_context_builder_filters_disabled():
    """ContextBuilder should not include disabled skills in system prompt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "hidden-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: hidden-skill\ndescription: Hidden\n---\n# Hidden")

        from nanobot.agent.context import ContextBuilder

        # Enabled: should appear
        builder = ContextBuilder(workspace)
        prompt = builder.build_system_prompt()
        assert "hidden-skill" in prompt

        # Disable via storage
        storage = HookStorage(workspace)
        storage.set_skill_enabled("hidden-skill", False)

        builder2 = ContextBuilder(workspace)
        prompt2 = builder2.build_system_prompt()
        assert "hidden-skill" not in prompt2


def test_disable_skill_via_hook_storage_directly():
    """HookStorage.set_skill_enabled() should persist disabled state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skill_dir = workspace / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: Test\n---\n# My Skill\n")

        storage = HookStorage(workspace)
        storage.set_skill_enabled("my-skill", False)
        assert storage.is_skill_disabled("my-skill")

        # Skill file should NOT be modified
        content = (skill_dir / "SKILL.md").read_text()
        assert "enabled: false" not in content


def test_reenable_skill_via_hook_storage():
    """Re-enabling a skill should remove it from disabled list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "skills").mkdir()

        storage = HookStorage(workspace)
        storage.set_skill_enabled("my-skill", False)
        assert storage.is_skill_disabled("my-skill")

        storage.set_skill_enabled("my-skill", True)
        assert not storage.is_skill_disabled("my-skill")


def test_load_skill_works_for_disabled():
    """load_skill() should still work for disabled skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "disabled"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: disabled\ndescription: Disabled\n---\n# Disabled Content\n")

        storage = HookStorage(workspace)
        storage.set_skill_enabled("disabled", False)

        loader = SkillsLoader(workspace)
        content = loader.load_skill("disabled")
        assert content is not None
        assert "Disabled Content" in content


def test_list_skills_includes_disabled():
    """list_skills() should include disabled skills (for management)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        for name in ["active", "paused"]:
            d = skills_dir / name
            d.mkdir()
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\n# {name}\n")

        storage = HookStorage(workspace)
        storage.set_skill_enabled("paused", False)

        loader = SkillsLoader(workspace)
        all_skills = loader.list_skills(filter_unavailable=False)
        names = [s["name"] for s in all_skills]

        assert "active" in names
        assert "paused" in names


def test_storage_persists_across_instances():
    """Hook storage state should persist across HookStorage instances."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        s1 = HookStorage(workspace)
        s1.set_skill_enabled("skill-a", False)

        s2 = HookStorage(workspace)
        assert s2.is_skill_disabled("skill-a")

        s2.set_skill_enabled("skill-a", True)

        s3 = HookStorage(workspace)
        assert not s3.is_skill_disabled("skill-a")
