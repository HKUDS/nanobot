import pytest
import os
import shutil
from pathlib import Path
from nanobot.agent.tools.shell import ExecTool

@pytest.mark.asyncio
async def test_exec_workspace_bypass(tmp_path):
    # Setup workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Create a file outside the workspace
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("sensitive")
    
    # Initialize tool with restriction
    tool = ExecTool(
        working_dir=str(workspace),
        restrict_to_workspace=True
    )
    
    # Attempt bypass via working_dir argument
    command = "rm secret.txt"
    result = await tool.execute(command, working_dir=str(outside_dir))
    
    assert "Error: Command blocked by safety guard (working_dir outside workspace)" in result
    assert secret_file.exists()

@pytest.mark.asyncio
async def test_exec_workspace_absolute_path(tmp_path):
    # Setup workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Create a file outside the workspace
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("sensitive")
    
    # Initialize tool with restriction
    tool = ExecTool(
        working_dir=str(workspace),
        restrict_to_workspace=True
    )
    
    # Attempt bypass via absolute path
    command = f"rm {outside_file}"
    result = await tool.execute(command, working_dir=str(workspace))
    
    assert "Error: Command blocked by safety guard (path outside working dir)" in result
    assert outside_file.exists()

@pytest.mark.asyncio
async def test_exec_workspace_safe_command(tmp_path):
    # Setup workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    safe_file = workspace / "safe.txt"
    safe_file.write_text("safe")
    
    # Initialize tool with restriction
    tool = ExecTool(
        working_dir=str(workspace),
        restrict_to_workspace=True
    )
    
    # Command inside workspace should work
    command = f"rm {safe_file}"
    result = await tool.execute(command, working_dir=str(workspace))
    
    assert "Exit code: 0" in result
    assert not safe_file.exists()
