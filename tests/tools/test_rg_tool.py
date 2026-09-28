"""Registration and exec delegation for ripgrep."""

import os
import shutil
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.rg import RgTool
from nanobot.agent.tools.search import FindFilesTool, GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.config.schema import ToolsConfig


@pytest.mark.parametrize("installed", [True, False])
@pytest.mark.parametrize("exec_enabled", [True, False])
@pytest.mark.parametrize("file_enabled", [True, False])
@pytest.mark.parametrize("scope", ["core", "subagent"])
def test_loader_selects_one_search_backend(tmp_path, monkeypatch, installed, exec_enabled, file_enabled, scope):
    monkeypatch.setattr("nanobot.agent.tools.rg.shutil.which", lambda *a, **kw: "rg" if installed else None)
    config = ToolsConfig()
    config.exec.enable = exec_enabled
    config.file.enable = file_enabled
    ctx = ToolContext(config=config, workspace=str(tmp_path))
    registry = ToolRegistry()
    ToolLoader(test_classes=[RgTool, GrepTool, FindFilesTool]).load(ctx, registry, scope=scope)
    expected = {"rg"} if installed and exec_enabled else {"grep", "find_files"}
    assert set(registry.tool_names) == (expected if file_enabled else set())


def test_detection_uses_exec_path_configuration(tmp_path, monkeypatch):
    config = ToolsConfig()
    config.exec.path_prepend = str(tmp_path / "before")
    config.exec.path_append = str(tmp_path / "after")
    captured = {}

    def which(command, *, path):
        captured.update(command=command, path=path)
        return "rg"

    monkeypatch.setattr("nanobot.agent.tools.rg.shutil.which", which)
    assert RgTool.enabled(ToolContext(config=config, workspace=str(tmp_path)))
    assert captured["path"] == os.pathsep.join([
        config.exec.path_prepend, os.environ.get("PATH", ""), config.exec.path_append,
    ])


async def test_rg_forwards_native_arguments_and_exec_options(monkeypatch):
    execute = AsyncMock(return_value="native output")
    monkeypatch.setattr(ExecTool, "execute", execute)
    arguments = '--engine=pcre2 --sort path --json "(?<=hello)world" .'
    result = await RgTool().execute(
        args=arguments, working_dir="project", timeout=12,
        yield_time_ms=25, max_output_chars=1500,
    )
    assert result == "native output"
    execute.assert_awaited_once_with(
        command="rg " + arguments, working_dir="project", timeout=12,
        yield_time_ms=25, max_output_chars=1500,
    )
    assert RgTool().read_only is False


def test_schema_exposes_arguments_and_exec_controls():
    schema = RgTool().parameters
    assert schema["properties"]["args"]["type"] == "string"
    assert schema["required"] == ["args"]
    assert {"working_dir", "shell", "timeout", "yield_time_ms"} <= schema["properties"].keys()
    assert "command" in ExecTool().parameters["properties"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
async def test_native_search_and_file_discovery_via_exec(tmp_path):
    (tmp_path / "source.py").write_text("before\nneedle\nafter\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("unrelated\n", encoding="utf-8")
    tool = RgTool(working_dir=str(tmp_path), restrict_to_workspace=True)
    result = await tool.execute(args='-n -C1 -g "*.py" needle .')
    assert "2:needle" in result
    assert "before" in result and "after" in result
    assert "Exit code: 0" in result
    files = await tool.execute(args='--files -g "*.py" .')
    assert "source.py" in files
    absent = await tool.execute(args="absent .")
    assert "Exit code: 1" in absent


async def test_exec_workspace_policy_applies(tmp_path):
    result = await RgTool(working_dir=str(tmp_path), restrict_to_workspace=True).execute(
        args="--files", working_dir=str(tmp_path.parent),
    )
    assert "outside the configured workspace" in result
