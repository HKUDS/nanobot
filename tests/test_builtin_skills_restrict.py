"""Tests for builtin skills access when restrictToWorkspace is enabled."""

import pytest
from pathlib import Path

from nanobot.agent.tools.filesystem import _resolve_path, ReadFileTool, ListDirTool, WriteFileTool, EditFileTool


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def builtin_skills_dir(tmp_path):
    """Create a temporary builtin skills directory (outside workspace)."""
    skills = tmp_path / "package" / "skills"
    skills.mkdir(parents=True)
    skill_dir = skills / "memory"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Memory Skill\nBuiltin skill content.")
    return skills


class TestResolvePathExtraReadDirs:
    """Test _resolve_path with extra_read_dirs parameter."""

    def test_allowed_dir_blocks_outside_path(self, workspace):
        """Path outside workspace is blocked when allowed_dir is set."""
        outside = workspace.parent / "outside.txt"
        outside.touch()
        with pytest.raises(PermissionError, match="outside allowed directory"):
            _resolve_path(str(outside), workspace=workspace, allowed_dir=workspace)

    def test_extra_read_dirs_allows_builtin_path(self, workspace, builtin_skills_dir):
        """Path in extra_read_dirs is allowed even with allowed_dir set."""
        skill_file = builtin_skills_dir / "memory" / "SKILL.md"
        result = _resolve_path(
            str(skill_file),
            workspace=workspace,
            allowed_dir=workspace,
            extra_read_dirs=[builtin_skills_dir],
        )
        assert result == skill_file.resolve()

    def test_extra_read_dirs_still_blocks_other_paths(self, workspace, builtin_skills_dir):
        """Paths not in workspace or extra_read_dirs are still blocked."""
        other = workspace.parent / "other.txt"
        other.touch()
        with pytest.raises(PermissionError, match="outside allowed directory"):
            _resolve_path(
                str(other),
                workspace=workspace,
                allowed_dir=workspace,
                extra_read_dirs=[builtin_skills_dir],
            )

    def test_workspace_path_still_works_with_extra_dirs(self, workspace, builtin_skills_dir):
        """Workspace paths still work when extra_read_dirs is set."""
        ws_file = workspace / "test.md"
        ws_file.touch()
        result = _resolve_path(
            str(ws_file),
            workspace=workspace,
            allowed_dir=workspace,
            extra_read_dirs=[builtin_skills_dir],
        )
        assert result == ws_file.resolve()

    def test_no_allowed_dir_ignores_extra_read_dirs(self, workspace, builtin_skills_dir):
        """When allowed_dir is None, any path is allowed (no restriction)."""
        outside = workspace.parent / "anywhere.txt"
        outside.touch()
        result = _resolve_path(str(outside), workspace=workspace, allowed_dir=None, extra_read_dirs=[builtin_skills_dir])
        assert result == outside.resolve()

    def test_extra_read_dirs_none_behaves_as_before(self, workspace):
        """When extra_read_dirs is None, behavior is unchanged."""
        outside = workspace.parent / "blocked.txt"
        outside.touch()
        with pytest.raises(PermissionError):
            _resolve_path(str(outside), workspace=workspace, allowed_dir=workspace, extra_read_dirs=None)


class TestReadFileToolExtraReadDirs:
    """Test ReadFileTool with extra_read_dirs for builtin skills."""

    @pytest.mark.asyncio
    async def test_read_builtin_skill(self, workspace, builtin_skills_dir):
        """ReadFileTool can read builtin skill files when extra_read_dirs is set."""
        tool = ReadFileTool(workspace=workspace, allowed_dir=workspace, extra_read_dirs=[builtin_skills_dir])
        skill_path = str(builtin_skills_dir / "memory" / "SKILL.md")
        result = await tool.execute(path=skill_path)
        assert "Memory Skill" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_read_builtin_skill_blocked_without_extra(self, workspace, builtin_skills_dir):
        """ReadFileTool blocks builtin skill files without extra_read_dirs."""
        tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
        skill_path = str(builtin_skills_dir / "memory" / "SKILL.md")
        result = await tool.execute(path=skill_path)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_read_workspace_file(self, workspace, builtin_skills_dir):
        """ReadFileTool can still read workspace files."""
        (workspace / "notes.md").write_text("hello")
        tool = ReadFileTool(workspace=workspace, allowed_dir=workspace, extra_read_dirs=[builtin_skills_dir])
        result = await tool.execute(path=str(workspace / "notes.md"))
        assert result == "hello"


class TestWriteFileToolNoExtraReadDirs:
    """Ensure WriteFileTool does NOT get extra_read_dirs (write stays restricted)."""

    @pytest.mark.asyncio
    async def test_write_outside_workspace_blocked(self, workspace, builtin_skills_dir):
        """WriteFileTool cannot write to builtin skills directory."""
        tool = WriteFileTool(workspace=workspace, allowed_dir=workspace)
        target = str(builtin_skills_dir / "memory" / "hack.md")
        result = await tool.execute(path=target, content="hacked")
        assert "Error" in result


class TestListDirToolExtraReadDirs:
    """Test ListDirTool with extra_read_dirs."""

    @pytest.mark.asyncio
    async def test_list_builtin_skills_dir(self, workspace, builtin_skills_dir):
        """ListDirTool can list builtin skills directory."""
        tool = ListDirTool(workspace=workspace, allowed_dir=workspace, extra_read_dirs=[builtin_skills_dir])
        result = await tool.execute(path=str(builtin_skills_dir))
        assert "memory" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_list_builtin_blocked_without_extra(self, workspace, builtin_skills_dir):
        """ListDirTool blocks builtin skills directory without extra_read_dirs."""
        tool = ListDirTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(path=str(builtin_skills_dir))
        assert "Error" in result
