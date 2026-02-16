from pathlib import Path

import pytest

from nanobot.agent.tools.filesystem import DeleteFileTool
from nanobot.agent.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_delete_file_success(tmp_path: Path) -> None:
    file_path = tmp_path / "to_delete.txt"
    file_path.write_text("data", encoding="utf-8")

    tool = DeleteFileTool()
    result = await tool.execute(path=str(file_path))

    assert result == f"Successfully deleted {file_path}"
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_delete_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"

    tool = DeleteFileTool()
    result = await tool.execute(path=str(missing))

    assert result == f"Error: File not found: {missing}"


@pytest.mark.asyncio
async def test_delete_file_rejects_directory(tmp_path: Path) -> None:
    dir_path = tmp_path / "folder"
    dir_path.mkdir()

    tool = DeleteFileTool()
    result = await tool.execute(path=str(dir_path))

    assert result == f"Error: Not a file: {dir_path}"


@pytest.mark.asyncio
async def test_delete_file_requires_path_parameter_via_schema(tmp_path: Path) -> None:
    file_path = tmp_path / "keep.txt"
    file_path.write_text("data", encoding="utf-8")

    registry = ToolRegistry()
    registry.register(DeleteFileTool())

    result = await registry.execute("delete_file", {})

    assert "Error: Invalid parameters for tool 'delete_file'" in result
    assert "missing required path" in result
    assert file_path.exists()


@pytest.mark.asyncio
async def test_delete_file_blocks_path_outside_allowed_dir(tmp_path: Path) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("data", encoding="utf-8")

    tool = DeleteFileTool(allowed_dir=allowed_dir)
    result = await tool.execute(path=str(outside_file))

    assert result == f"Error: Path {outside_file} is outside allowed directory {allowed_dir}"
    assert outside_file.exists()


@pytest.mark.asyncio
async def test_delete_file_removes_symlink_not_target(tmp_path: Path) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()

    target = tmp_path / "target.txt"
    target.write_text("data", encoding="utf-8")

    link = allowed_dir / "target_link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    tool = DeleteFileTool(allowed_dir=allowed_dir)
    result = await tool.execute(path=str(link))

    assert result == f"Successfully deleted {link}"
    assert not link.exists()
    assert target.exists()


@pytest.mark.asyncio
async def test_delete_file_blocks_symlinked_parent_escape(tmp_path: Path) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    outside_file = outside_dir / "outside.txt"
    outside_file.write_text("data", encoding="utf-8")

    escaped_parent = allowed_dir / "escape"
    try:
        escaped_parent.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    tool = DeleteFileTool(allowed_dir=allowed_dir)
    escaped_path = escaped_parent / "outside.txt"
    result = await tool.execute(path=str(escaped_path))

    assert result == f"Error: Path {escaped_path} is outside allowed directory {allowed_dir}"
    assert outside_file.exists()


@pytest.mark.asyncio
async def test_delete_file_allows_symlinked_allowed_dir(tmp_path: Path) -> None:
    real_workspace = tmp_path / "real_workspace"
    real_workspace.mkdir()

    allowed_link = tmp_path / "workspace_link"
    try:
        allowed_link.symlink_to(real_workspace, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    file_via_link = allowed_link / "inside.txt"
    file_via_link.write_text("data", encoding="utf-8")

    tool = DeleteFileTool(allowed_dir=allowed_link)
    result = await tool.execute(path=str(file_via_link))

    assert result == f"Successfully deleted {file_via_link}"
    assert not file_via_link.exists()
