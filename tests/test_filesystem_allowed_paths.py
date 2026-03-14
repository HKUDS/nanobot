import pytest

from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool


class TestFilesystemAllowedPaths:
    @pytest.mark.asyncio
    async def test_read_file_allows_extra_allowed_dir(self, tmp_path):
        extra_dir = tmp_path / "allowed-extra"
        extra_dir.mkdir()
        sample = extra_dir / "sample.txt"
        sample.write_text("hello", encoding="utf-8")

        tool = ReadFileTool(workspace=tmp_path, allowed_paths=[tmp_path, extra_dir])
        result = await tool.execute(path=str(sample))

        assert "hello" in result

    @pytest.mark.asyncio
    async def test_write_file_blocks_path_outside_all_allowed_paths(self, tmp_path):
        extra_dir = tmp_path / "allowed-extra"
        extra_dir.mkdir()
        outside_dir = tmp_path.parent / "outside-dir"
        outside_file = outside_dir / "blocked.txt"

        tool = WriteFileTool(workspace=tmp_path, allowed_paths=[tmp_path, extra_dir])
        result = await tool.execute(path=str(outside_file), content="nope")

        assert "outside allowed paths" in result
