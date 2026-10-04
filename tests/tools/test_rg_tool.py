"""Registration and exec delegation for ripgrep."""

import asyncio
import os
import re
import shlex
import shutil
import sys
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.rg import RgTool
from nanobot.agent.tools.search import FindFilesTool, GrepTool
from nanobot.agent.tools.shell import ExecTool, _PreparedCommand
from nanobot.config.schema import ToolsConfig


@pytest.mark.parametrize("installed", [True, False])
@pytest.mark.parametrize("exec_enabled", [True, False])
@pytest.mark.parametrize("file_enabled", [True, False])
@pytest.mark.parametrize("scope", ["core", "subagent"])
@pytest.mark.parametrize("classes", [
    [RgTool, GrepTool, FindFilesTool], [GrepTool, FindFilesTool, RgTool],
])
def test_loader_selects_one_search_backend(tmp_path, monkeypatch, installed, exec_enabled, file_enabled, scope, classes):
    monkeypatch.setattr("nanobot.agent.tools.rg.shutil.which", lambda *a, **kw: "rg" if installed else None)
    config = ToolsConfig()
    config.exec.enable = exec_enabled
    config.file.enable = file_enabled
    ctx = ToolContext(config=config, workspace=str(tmp_path))
    registry = ToolRegistry()
    registered = ToolLoader(test_classes=classes).load(ctx, registry, scope=scope)
    expected = {"rg"} if installed and exec_enabled else {"grep", "find_files"}
    assert set(registry.tool_names) == (expected if file_enabled else set())
    assert set(registered) == set(registry.tool_names)


def test_loader_keeps_builtin_search_when_rg_creation_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(RgTool, "enabled", classmethod(lambda cls, ctx: True))

    def fail_create(cls, ctx):
        raise RuntimeError("rg initialization failed")

    monkeypatch.setattr(RgTool, "create", classmethod(fail_create))
    registry = ToolRegistry()
    registered = ToolLoader(test_classes=[RgTool, GrepTool, FindFilesTool]).load(
        ToolContext(config=ToolsConfig(), workspace=str(tmp_path)), registry,
    )
    assert set(registered) == {"grep", "find_files"}
    assert set(registry.tool_names) == {"grep", "find_files"}


def test_loader_can_load_builtin_search_independently(tmp_path, monkeypatch):
    monkeypatch.setattr(RgTool, "enabled", classmethod(lambda cls, ctx: True))
    registry = ToolRegistry()
    registered = ToolLoader(test_classes=[GrepTool, FindFilesTool]).load(
        ToolContext(config=ToolsConfig(), workspace=str(tmp_path)), registry,
    )
    assert set(registered) == {"grep", "find_files"}
    assert set(registry.tool_names) == {"grep", "find_files"}


def test_loader_preserves_plugin_search_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(RgTool, "enabled", classmethod(lambda cls, ctx: True))
    loader = ToolLoader(test_classes=[RgTool, GrepTool, FindFilesTool])
    monkeypatch.setattr(loader, "_discover_plugins", lambda: {"external_grep": GrepTool})
    registry = ToolRegistry()
    registered = loader.load(ToolContext(config=ToolsConfig(), workspace=str(tmp_path)), registry)
    assert registered == ["rg", "grep"]
    assert set(registry.tool_names) == {"rg", "grep"}


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
    arguments = ["--engine=pcre2", "--sort", "path", "--json", "(?<=hello)world", "."]
    result = await RgTool().execute(
        args=arguments, working_dir="project", timeout=12,
        yield_time_ms=25, max_output_chars=1500,
    )
    assert result == "native output"
    execute.assert_awaited_once_with(
        command=["rg", *arguments], working_dir="project", timeout=12,
        yield_time_ms=25, max_output_chars=1500,
    )
    assert RgTool().read_only is False


def test_schema_exposes_arguments_and_exec_controls():
    schema = RgTool().parameters
    assert schema["properties"]["args"]["type"] == "array"
    assert schema["properties"]["args"]["items"] == {"type": "string"}
    assert schema["required"] == ["args"]
    assert {"working_dir", "timeout", "yield_time_ms"} <= schema["properties"].keys()
    assert "command" in ExecTool().parameters["properties"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
async def test_native_search_and_file_discovery_via_exec(tmp_path):
    (tmp_path / "source.py").write_text("before\nneedle\nafter\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("unrelated\n", encoding="utf-8")
    tool = RgTool(working_dir=str(tmp_path), restrict_to_workspace=False)
    result = await tool.execute(args=["-n", "-C1", "-g", "*.py", "needle", "."])
    assert "2:needle" in result
    assert "before" in result and "after" in result
    assert "Exit code: 0" in result
    files = await tool.execute(args=["--files", "-g", "*.py", "."])
    assert "source.py" in files
    absent = await tool.execute(args=["absent", "."])
    assert "Exit code: 1" in absent


async def test_exec_workspace_policy_applies(tmp_path):
    result = await RgTool(working_dir=str(tmp_path), restrict_to_workspace=True).execute(
        args=["--files"], working_dir=str(tmp_path.parent),
    )
    assert "outside the configured workspace" in result


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
async def test_native_arguments_preserve_spaces_and_shell_characters(tmp_path):
    text = 'hello world | $HOME > output; "quoted" & $(echo hi)'
    (tmp_path / "space name.txt").write_text(text + "\n", encoding="utf-8")
    tool = RgTool(working_dir=str(tmp_path))
    result = await tool.execute(args=["-n", "-F", "--", text, "space name.txt"])
    assert f"1:{text}" in result
    assert "Exit code: 0" in result


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
async def test_native_search_session(tmp_path):
    (tmp_path / "source.txt").write_text("needle\n", encoding="utf-8")
    manager = ExecSessionManager()
    tool = RgTool(working_dir=str(tmp_path), session_manager=manager)
    try:
        result = await tool.execute(args=["-n", "needle", "."], yield_time_ms=0)
        session = re.search(r"session_id:\s*([0-9a-f]+)", result)
        if session:
            poll = await manager.write(
                session_id=session.group(1), chars=None, close_stdin=False, terminate=False,
                yield_time_ms=10000, max_output_chars=1000,
            )
            result += poll.output
            assert poll.exit_code == 0
        assert "1:needle" in result
    finally:
        await manager.close_all()


async def test_direct_process_preserves_arguments_and_output_limit(tmp_path):
    tool = ExecTool(working_dir=str(tmp_path))
    result = await tool.execute(
        command=[sys.executable, "-c", "print('x' * 4000)"], max_output_chars=1000,
    )
    assert "chars truncated" in result
    assert "Exit code: 0" in result


async def test_direct_process_timeout(tmp_path):
    result = await ExecTool(working_dir=str(tmp_path)).execute(
        command=[sys.executable, "-c", "import time; time.sleep(20)"], timeout=1,
    )
    assert "timed out after 1 seconds" in result


async def test_direct_process_cancellation_reaps_child(tmp_path, monkeypatch):
    spawned = asyncio.Event()
    processes = []
    original_spawn = ExecTool._spawn

    async def capture(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        spawned.set()
        return process

    monkeypatch.setattr(ExecTool, "_spawn", staticmethod(capture))
    task = asyncio.create_task(ExecTool(working_dir=str(tmp_path)).execute(
        command=[sys.executable, "-c", "import time; time.sleep(20)"],
    ))
    await asyncio.wait_for(spawned.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(processes[0].returncode, int)


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
async def test_direct_search_uses_configured_path(tmp_path, monkeypatch):
    installed = shutil.which("rg")
    assert installed
    bin_dir = tmp_path / "custom bin"
    bin_dir.mkdir()
    shutil.copy2(installed, bin_dir / ("rg.exe" if sys.platform == "win32" else "rg"))
    monkeypatch.setenv("PATH", "")
    result = await RgTool(working_dir=str(tmp_path), path_prepend=str(bin_dir)).execute(
        args=["--version"],
    )
    assert "ripgrep" in result
    assert "Exit code: 0" in result


@pytest.mark.parametrize("backend", ["bwrap", "seatbelt"])
def test_direct_search_preserves_sandbox_and_arguments(tmp_path, monkeypatch, backend):
    monkeypatch.setattr("nanobot.agent.tools.shell._IS_WINDOWS", False)
    launcher = str(tmp_path / "trusted launcher")
    monkeypatch.setattr(
        "nanobot.agent.tools.sandbox.resolve_sandbox_launcher", lambda name: launcher,
    )
    args = ["rg", "-F", "hello | $HOME; 'world'", "."]
    prepared = RgTool(
        working_dir=str(tmp_path), restrict_to_workspace=True, sandbox=backend,
    )._prepare_command(args)
    assert isinstance(prepared, _PreparedCommand)
    assert isinstance(prepared.command, list)
    assert prepared.command[0] == launcher
    assert prepared.command[-2] == "-c"
    inner_command = prepared.command[-1].split("\n")[-1]
    assert shlex.split(inner_command) == args
