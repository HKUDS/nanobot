"""Tests for ManageSkillTool: sandbox skill creation with enforced frontmatter."""

from unittest.mock import patch

import pytest

from nanobot.agent.tools.filesystem import ManageSkillTool


@pytest.fixture()
def tool(tmp_path):
    return ManageSkillTool(workspace=tmp_path, allowed_dir=tmp_path)


@pytest.fixture()
def builtin_dir(tmp_path):
    """Fake builtin skills directory with a 'weather' skill."""
    builtin = tmp_path / "builtin_skills"
    builtin.mkdir()
    (builtin / "weather").mkdir()
    (builtin / "weather" / "SKILL.md").write_text(
        "---\nname: weather\ndescription: Get weather info\n---\n\n# Weather", encoding="utf-8"
    )
    return builtin


def _read_skill(workspace, name):
    return (workspace / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestManageSkillHappyPath:

    @pytest.mark.asyncio
    async def test_create_skill(self, tool, tmp_path):
        result = await tool.execute(
            skill_name="fetch-logs",
            description="How to fetch service logs",
            instructions="# Fetch Logs\n\n1. Run `kubectl logs`",
        )
        assert "Successfully" in result
        assert "fetch-logs" in result

        content = _read_skill(tmp_path, "fetch-logs")
        assert content.startswith("---\n")
        assert "name: fetch-logs" in content
        assert "description: 'How to fetch service logs'" in content
        assert "kubectl logs" in content

    @pytest.mark.asyncio
    async def test_overwrite_existing_skill(self, tool, tmp_path):
        await tool.execute(
            skill_name="my-skill",
            description="v1",
            instructions="old content",
        )
        await tool.execute(
            skill_name="my-skill",
            description="v2",
            instructions="new content",
        )
        content = _read_skill(tmp_path, "my-skill")
        assert "v2" in content
        assert "new content" in content
        assert "v1" not in content


# ---------------------------------------------------------------------------
# Name sanitization
# ---------------------------------------------------------------------------

class TestNameSanitization:

    @pytest.mark.asyncio
    async def test_uppercase_to_lowercase(self, tool, tmp_path):
        await tool.execute(skill_name="MySkill", description="d", instructions="i")
        assert (tmp_path / "skills" / "myskill" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_spaces_to_hyphens(self, tool, tmp_path):
        await tool.execute(skill_name="fetch logs", description="d", instructions="i")
        assert (tmp_path / "skills" / "fetch-logs" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_special_chars_stripped(self, tool, tmp_path):
        await tool.execute(skill_name="foo@bar!baz", description="d", instructions="i")
        assert (tmp_path / "skills" / "foo-bar-baz" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_leading_trailing_hyphens_stripped(self, tool, tmp_path):
        await tool.execute(skill_name="--fetch-logs--", description="d", instructions="i")
        assert (tmp_path / "skills" / "fetch-logs" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_slashes_removed(self, tool, tmp_path):
        await tool.execute(skill_name="../../../etc/passwd", description="d", instructions="i")
        name_dir = tmp_path / "skills"
        dirs = [d.name for d in name_dir.iterdir()]
        assert len(dirs) == 1
        assert "--etc-passwd" in dirs[0] or "etc-passwd" in dirs[0]

    @pytest.mark.asyncio
    async def test_invalid_name_all_special(self, tool):
        result = await tool.execute(skill_name="!!!@@@", description="d", instructions="i")
        assert "Error" in result
        assert "invalid skill name" in result

    @pytest.mark.asyncio
    async def test_empty_name(self, tool):
        result = await tool.execute(skill_name="", description="d", instructions="i")
        assert "Error" in result


# ---------------------------------------------------------------------------
# Built-in skill collision guard
# ---------------------------------------------------------------------------

class TestBuiltinCollisionGuard:

    @pytest.mark.asyncio
    async def test_rejects_builtin_skill_name(self, tool, builtin_dir):
        with patch("nanobot.agent.skills.BUILTIN_SKILLS_DIR", builtin_dir):
            result = await tool.execute(
                skill_name="weather",
                description="My weather thing",
                instructions="Do stuff",
            )
        assert "Error" in result
        assert "conflicts with a built-in skill" in result


# ---------------------------------------------------------------------------
# YAML frontmatter formatting
# ---------------------------------------------------------------------------

class TestFrontmatterFormatting:

    @pytest.mark.asyncio
    async def test_description_with_single_quotes(self, tool, tmp_path):
        await tool.execute(
            skill_name="quote-test",
            description="It's a test",
            instructions="content",
        )
        content = _read_skill(tmp_path, "quote-test")
        # Single quotes in description should be escaped as ''
        assert "It''s a test" in content

    @pytest.mark.asyncio
    async def test_description_with_colon(self, tool, tmp_path):
        await tool.execute(
            skill_name="colon-test",
            description="How to: fetch logs",
            instructions="content",
        )
        content = _read_skill(tmp_path, "colon-test")
        # Should be safely quoted
        assert "'How to: fetch logs'" in content

    @pytest.mark.asyncio
    async def test_description_with_hash(self, tool, tmp_path):
        await tool.execute(
            skill_name="hash-test",
            description="Use # for comments",
            instructions="content",
        )
        content = _read_skill(tmp_path, "hash-test")
        assert "'Use # for comments'" in content

    @pytest.mark.asyncio
    async def test_frontmatter_has_name_field(self, tool, tmp_path):
        await tool.execute(
            skill_name="named-skill",
            description="A skill",
            instructions="steps",
        )
        content = _read_skill(tmp_path, "named-skill")
        assert "name: named-skill\n" in content

    @pytest.mark.asyncio
    async def test_body_after_frontmatter(self, tool, tmp_path):
        body = "# Step 1\nDo thing\n\n# Step 2\nDo other thing"
        await tool.execute(
            skill_name="body-test",
            description="d",
            instructions=body,
        )
        content = _read_skill(tmp_path, "body-test")
        assert content.endswith(body)


# ---------------------------------------------------------------------------
# Missing parameters
# ---------------------------------------------------------------------------

class TestMissingParameters:

    @pytest.mark.asyncio
    async def test_missing_skill_name(self, tool):
        result = await tool.execute(skill_name=None, description="d", instructions="i")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_missing_description(self, tool):
        result = await tool.execute(skill_name="x", description=None, instructions="i")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_missing_instructions(self, tool):
        result = await tool.execute(skill_name="x", description="d", instructions=None)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_empty_skill_name(self, tool):
        result = await tool.execute(skill_name="", description="d", instructions="i")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_no_args_at_all(self, tool):
        result = await tool.execute()
        assert "Error" in result
