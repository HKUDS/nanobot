import pytest

from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool


class TestFilesystemAllowedPaths:
    @pytest.mark.asyncio
    async def test_read_file_blocks_path_outside_workspace_when_restricted(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("top-secret", encoding="utf-8")

        tool = ReadFileTool(workspace=workspace, allowed_paths=[workspace])
        result = await tool.execute(path=str(outside_file))

        assert "outside allowed paths" in result

    @pytest.mark.asyncio
    async def test_read_file_allows_extra_allowed_path(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        extra_dir = tmp_path / "allowed-extra"
        extra_dir.mkdir()
        sample = extra_dir / "sample.txt"
        sample.write_text("hello", encoding="utf-8")

        tool = ReadFileTool(workspace=workspace, allowed_paths=[workspace, extra_dir])
        result = await tool.execute(path=str(sample))

        assert "hello" in result

    @pytest.mark.asyncio
    async def test_read_file_allows_sibling_media_dir_when_allowlisted(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        media_dir = tmp_path / "media"
        media_dir.mkdir()
        uploaded = media_dir / "upload.txt"
        uploaded.write_text("uploaded content", encoding="utf-8")

        tool = ReadFileTool(workspace=workspace, allowed_paths=[workspace, media_dir])
        result = await tool.execute(path=str(uploaded))

        assert "uploaded content" in result

    @pytest.mark.asyncio
    async def test_write_file_blocks_path_outside_all_allowed_paths(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        extra_dir = tmp_path / "allowed-extra-write"
        extra_dir.mkdir()
        outside_dir = tmp_path / "outside-dir"
        outside_dir.mkdir()
        outside_file = outside_dir / "blocked.txt"

        tool = WriteFileTool(workspace=workspace, allowed_paths=[workspace, extra_dir])
        result = await tool.execute(path=str(outside_file), content="nope")

        assert "outside allowed paths" in result
