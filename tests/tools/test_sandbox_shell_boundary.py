"""Native isolation at the public exec boundary, using synthetic canaries only."""

import os
import re
import shlex
import shutil
import sys

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool
from nanobot.agent.tools.shell import ExecTool

BACKEND = "seatbelt" if sys.platform == "darwin" else "bwrap"
pytestmark = pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"}
    or shutil.which("sandbox-exec" if BACKEND == "seatbelt" else "bwrap") is None,
    reason="requires a native Unix sandbox",
)


@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("symlink", [False, True])
@pytest.mark.parametrize("shell_name", ["bash", "sh", "zsh"])
async def test_selected_shell_runs_inside_sandbox(tmp_path, monkeypatch, session, symlink, shell_name):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-canary"
    outside.write_text("unchanged")
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    script = workspace / ("interpreter" if symlink else shell_name)
    script.write_text(
        "#!/bin/sh\n"
        f"cat {shlex.quote(str(outside))}\n"
        f"printf escaped > {shlex.quote(str(outside))}\n"
        "printf contained > inside-canary\n"
        "printf shell-ran\n"
    )
    script.chmod(0o700)
    shell = workspace / shell_name
    if symlink:
        shell.symlink_to(script)
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(workspace), sandbox=BACKEND, session_manager=manager)
    try:
        result = await tool.execute(
            command="printf legitimate", shell=str(shell), timeout=5,
            yield_time_ms=0 if session else None,
        )
        match = re.search(r"session_id:\s*([0-9a-f]+)", result)
        if match:
            final = await ExecSessionTool(manager=manager).execute(
                session_id=match.group(1), until_exit=True, timeout_ms=5000,
            )
            result = f"{result}\n{final}"
    finally:
        await manager.close_all()
    assert "Exit code: 0" in result, result
    assert "shell-ran" in result, result
    assert "unchanged" not in result
    assert outside.read_text() == "unchanged"
    assert (workspace / "inside-canary").read_text() == "contained"


async def test_sandboxed_shell_preserves_ordinary_bash_commands(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    tool = ExecTool(working_dir=str(tmp_path), sandbox=BACKEND)
    result = await tool.execute(command="items=(hello world); printf '%s' \"${items[1]}\"", shell="bash")
    assert result.startswith("world\nExit code: 0\n"), result


async def test_configured_path_cannot_replace_sandbox_launcher(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    impostor = tmp_path / ("sandbox-exec" if BACKEND == "seatbelt" else "bwrap")
    impostor.write_text("#!/bin/sh\nprintf shadowed-launcher")
    impostor.chmod(0o700)
    tool = ExecTool(working_dir=str(tmp_path), sandbox=BACKEND, path_prepend=str(tmp_path))
    result = await tool.execute(command="printf contained")
    assert result.startswith("contained\nExit code: 0\n"), result


async def test_login_profile_runs_inside_sandbox(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-canary"
    outside.write_text("unchanged")
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    (workspace / ".bash_profile").write_text(
        f"printf escaped > {shlex.quote(str(outside))}\n"
        "export SANDBOX_PROFILE_LOADED=yes\n"
    )
    tool = ExecTool(working_dir=str(workspace), sandbox=BACKEND)
    result = await tool.execute(command='printf "%s" "$SANDBOX_PROFILE_LOADED"', shell="bash", login=True)
    assert "yes" in result, result
    assert outside.read_text() == "unchanged"


async def test_parent_path_cannot_replace_sandbox_launcher(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-canary"
    outside.write_text("unchanged")
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    impostor = workspace / ("sandbox-exec" if BACKEND == "seatbelt" else "bwrap")
    impostor.write_text(
        "#!/bin/sh\n"
        f"printf escaped > {shlex.quote(str(outside))}\n"
        "printf shadowed-launcher\n"
    )
    impostor.chmod(0o700)
    monkeypatch.setenv("PATH", f"{workspace}{os.pathsep}{os.defpath}")
    tool = ExecTool(working_dir=str(workspace), sandbox=BACKEND)

    result = await tool.execute(command="printf contained")

    assert result.startswith("contained\nExit code: 0\n"), result
    assert outside.read_text() == "unchanged"


async def test_missing_launcher_does_not_run_command_unsandboxed(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    original_which = shutil.which
    launcher = "/usr/bin/sandbox-exec" if BACKEND == "seatbelt" else "bwrap"
    monkeypatch.setattr(
        "nanobot.agent.tools.shell.shutil.which",
        lambda name, **kwargs: None if name == launcher else original_which(name, **kwargs),
    )
    tool = ExecTool(working_dir=str(tmp_path), sandbox=BACKEND)

    result = await tool.execute(command="printf ran > must-not-exist")

    assert "sandbox launcher not found" in result
    assert not (tmp_path / "must-not-exist").exists()


async def test_trusted_shell_completion_preserves_sandbox(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    tool = ExecTool(working_dir=str(workspace), sandbox=BACKEND)

    result = await tool.execute_to_completion("printf complete > result", str(workspace))

    assert "Exit code: 0" in result, result
    assert (workspace / "result").read_text() == "complete"


async def test_sandbox_preserves_literal_argument_vector(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
    tool = ExecTool(working_dir=str(tmp_path), sandbox=BACKEND)
    literal = "hello | $HOME; 'world'"

    result = await tool.execute(command=["printf", "%s", literal])

    assert result.startswith(f"{literal}\nExit code: 0\n"), result
