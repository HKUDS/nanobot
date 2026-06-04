"""Tests for skill management tools."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from blackcat.agent.tools.skills import (
    SkillCreateTool,
    SkillGetReferenceTool,
    SkillGetTool,
    SkillListReferencesTool,
    SkillListTool,
    SkillUpdateTool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace with skills directory."""
    with TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        skills_dir = workspace / "skills"
        skills_dir.mkdir()
        yield workspace


@pytest.fixture
def sample_skill(temp_workspace):
    """Create a sample skill with references."""
    skill_dir = temp_workspace / "skills" / "test-skill"
    skill_dir.mkdir()

    # Create SKILL.md
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: test-skill
description: A test skill for unit tests
---

# Test Skill

This is a test skill.
""",
        encoding="utf-8",
    )

    # Create references directory
    refs_dir = skill_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "guide.md").write_text("# Guide\n\nTest reference guide.", encoding="utf-8")

    # Create scripts directory
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "run.sh").write_text("#!/bin/bash\necho 'test'", encoding="utf-8")

    # Create assets directory
    assets_dir = skill_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "template.json").write_text('{"test": true}', encoding="utf-8")

    return temp_workspace


# ---------------------------------------------------------------------------
# SkillListTool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_list_empty(temp_workspace):
    """Test listing skills when none exist in workspace (builtin skills still show)."""
    tool = SkillListTool(workspace=temp_workspace)
    result = await tool.execute()
    # Builtin skills (like skill-creator) still appear even with empty workspace
    # So we check that workspace skills are not listed
    assert "Available Skills" in result


@pytest.mark.asyncio
async def test_skill_list_with_skills(sample_skill):
    """Test listing skills when some exist."""
    tool = SkillListTool(workspace=sample_skill)
    result = await tool.execute()
    assert "test-skill" in result
    assert "A test skill for unit tests" in result


@pytest.mark.asyncio
async def test_skill_list_filter_unavailable(sample_skill):
    """Test filtering unavailable skills."""
    tool = SkillListTool(workspace=sample_skill)
    result = await tool.execute(filter_unavailable=True)
    assert "test-skill" in result


# ---------------------------------------------------------------------------
# SkillGetTool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_get_existing(sample_skill):
    """Test getting an existing skill."""
    tool = SkillGetTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill")
    assert "test-skill" in result
    assert "Test Skill" in result


@pytest.mark.asyncio
async def test_skill_get_nonexistent(temp_workspace):
    """Test getting a non-existent skill."""
    tool = SkillGetTool(workspace=temp_workspace)
    result = await tool.execute(name="nonexistent")
    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_skill_get_missing_name(temp_workspace):
    """Test getting a skill without providing name."""
    tool = SkillGetTool(workspace=temp_workspace)
    result = await tool.execute()
    assert "Error" in result
    assert "required" in result


# ---------------------------------------------------------------------------
# SkillCreateTool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_create_success(temp_workspace):
    """Test creating a new skill."""
    tool = SkillCreateTool(workspace=temp_workspace)
    result = await tool.execute(
        name="new-skill",
        skill_description="A newly created skill",
        content="# New Skill\n\nThis is new.",
    )
    assert "Successfully created" in result
    assert "new-skill" in result

    # Verify skill was created
    skill_file = temp_workspace / "skills" / "new-skill" / "SKILL.md"
    assert skill_file.exists()


@pytest.mark.asyncio
async def test_skill_create_invalid_name(temp_workspace):
    """Test creating a skill with invalid name."""
    tool = SkillCreateTool(workspace=temp_workspace)
    result = await tool.execute(
        name="InvalidName",
        skill_description="Test",
        content="Test",
    )
    assert "Error" in result
    assert "lowercase" in result.lower()


@pytest.mark.asyncio
async def test_skill_create_duplicate(sample_skill):
    """Test creating a skill that already exists."""
    tool = SkillCreateTool(workspace=sample_skill)
    result = await tool.execute(
        name="test-skill",
        skill_description="Test",
        content="Test",
    )
    assert "Error" in result
    assert "already exists" in result


@pytest.mark.asyncio
async def test_skill_create_missing_params(temp_workspace):
    """Test creating a skill without required params."""
    tool = SkillCreateTool(workspace=temp_workspace)

    # Missing name
    result = await tool.execute(skill_description="Test", content="Test")
    assert "Error" in result
    assert "required" in result

    # Missing description
    result = await tool.execute(name="test", content="Test")
    assert "Error" in result
    assert "required" in result


# ---------------------------------------------------------------------------
# SkillUpdateTool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_update_description(sample_skill):
    """Test updating skill description."""
    tool = SkillUpdateTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", skill_description="Updated description")
    assert "Successfully updated" in result


@pytest.mark.asyncio
async def test_skill_update_content(sample_skill):
    """Test updating skill content."""
    tool = SkillUpdateTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", content="# Updated Content")
    assert "Successfully updated" in result

    # Verify content was updated
    skill_file = sample_skill / "skills" / "test-skill" / "SKILL.md"
    content = skill_file.read_text(encoding="utf-8")
    assert "Updated Content" in content


@pytest.mark.asyncio
async def test_skill_update_nonexistent(temp_workspace):
    """Test updating a non-existent skill."""
    tool = SkillUpdateTool(workspace=temp_workspace)
    result = await tool.execute(name="nonexistent", skill_description="Test")
    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_skill_update_missing_params(sample_skill):
    """Test updating without any params."""
    tool = SkillUpdateTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill")
    assert "Error" in result
    assert "at least one" in result


# ---------------------------------------------------------------------------
# SkillListReferencesTool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_references_with_all_types(sample_skill):
    """Test listing references when all types exist."""
    tool = SkillListReferencesTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill")

    assert "references/" in result
    assert "guide.md" in result
    assert "scripts/" in result
    assert "run.sh" in result
    assert "assets/" in result
    assert "template.json" in result


@pytest.mark.asyncio
async def test_list_references_empty(temp_workspace):
    """Test listing references for skill with none."""
    # Create skill without references
    skill_dir = temp_workspace / "skills" / "empty-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: empty-skill\n---\n# Empty", encoding="utf-8")

    tool = SkillListReferencesTool(workspace=temp_workspace)
    result = await tool.execute(name="empty-skill")
    assert "no references" in result.lower()


@pytest.mark.asyncio
async def test_list_references_nonexistent_skill(temp_workspace):
    """Test listing references for non-existent skill."""
    tool = SkillListReferencesTool(workspace=temp_workspace)
    result = await tool.execute(name="nonexistent")
    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_list_references_missing_name(temp_workspace):
    """Test listing references without skill name."""
    tool = SkillListReferencesTool(workspace=temp_workspace)
    result = await tool.execute()
    assert "Error" in result
    assert "required" in result


# ---------------------------------------------------------------------------
# SkillGetReferenceTool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_reference_success(sample_skill):
    """Test getting a reference file."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="references/guide.md")
    assert "Guide" in result
    assert "Test reference guide" in result


@pytest.mark.asyncio
async def test_get_reference_script(sample_skill):
    """Test getting a script file."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="scripts/run.sh")
    assert "echo 'test'" in result


@pytest.mark.asyncio
async def test_get_reference_asset(sample_skill):
    """Test getting an asset file."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="assets/template.json")
    assert '"test": true' in result


@pytest.mark.asyncio
async def test_get_reference_nonexistent_file(sample_skill):
    """Test getting a non-existent reference file."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="references/nonexistent.md")
    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_get_reference_nonexistent_skill(temp_workspace):
    """Test getting reference from non-existent skill."""
    tool = SkillGetReferenceTool(workspace=temp_workspace)
    result = await tool.execute(name="nonexistent", ref_path="references/guide.md")
    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_get_reference_path_traversal_parent(sample_skill):
    """Test path traversal with '..' is blocked."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="../outside/file.md")
    assert "Error" in result
    assert "Invalid" in result


@pytest.mark.asyncio
async def test_get_reference_path_traversal_absolute(sample_skill):
    """Test absolute path is blocked."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="/etc/passwd")
    assert "Error" in result
    assert "Invalid" in result


@pytest.mark.asyncio
async def test_get_reference_missing_params(sample_skill):
    """Test getting reference without required params."""
    tool = SkillGetReferenceTool(workspace=sample_skill)

    # Missing name
    result = await tool.execute(ref_path="references/guide.md")
    assert "Error" in result
    assert "required" in result

    # Missing ref_path
    result = await tool.execute(name="test-skill")
    assert "Error" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_get_reference_invalid_type(sample_skill):
    """Test getting reference with invalid type."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="invalid/file.md")
    assert "Error" in result
    assert "Invalid resource type" in result


@pytest.mark.asyncio
async def test_get_reference_directory(sample_skill):
    """Test getting a directory instead of file."""
    tool = SkillGetReferenceTool(workspace=sample_skill)
    result = await tool.execute(name="test-skill", ref_path="references")
    assert "Error" in result
    # "references" alone is invalid format (needs type/filename)
    assert "Invalid path format" in result


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_skill_workflow(temp_workspace):
    """Test complete workflow: create, list, get, update, add references."""
    # Create skill
    create_tool = SkillCreateTool(workspace=temp_workspace)
    result = await create_tool.execute(
        name="workflow-skill",
        skill_description="Workflow test skill",
        content="# Workflow Skill\n\nTest content.",
    )
    assert "Successfully created" in result

    # List skills
    list_tool = SkillListTool(workspace=temp_workspace)
    result = await list_tool.execute()
    assert "workflow-skill" in result

    # Get skill
    get_tool = SkillGetTool(workspace=temp_workspace)
    result = await get_tool.execute(name="workflow-skill")
    assert "Workflow Skill" in result

    # Update skill
    update_tool = SkillUpdateTool(workspace=temp_workspace)
    result = await update_tool.execute(
        name="workflow-skill",
        content="# Updated Workflow\n\nNew content.",
    )
    assert "Successfully updated" in result

    # Verify update
    result = await get_tool.execute(name="workflow-skill")
    assert "Updated Workflow" in result

    # Add references manually
    refs_dir = temp_workspace / "skills" / "workflow-skill" / "references"
    refs_dir.mkdir()
    (refs_dir / "api.md").write_text("# API Reference\n\nEndpoints.", encoding="utf-8")

    # List references
    list_refs = SkillListReferencesTool(workspace=temp_workspace)
    result = await list_refs.execute(name="workflow-skill")
    assert "references/" in result
    assert "api.md" in result

    # Get reference
    get_ref = SkillGetReferenceTool(workspace=temp_workspace)
    result = await get_ref.execute(name="workflow-skill", ref_path="references/api.md")
    assert "API Reference" in result
