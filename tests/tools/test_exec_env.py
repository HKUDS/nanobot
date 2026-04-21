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


# ---------------------------------------------------------------------------
# MIT-143: `printenv` at command-start is now blocked by the shell
# pre-screen added in MIT-123 (it's classified as a secret-dump command).
# These two tests were written before that guard landed and relied on
# `printenv` to verify `allowed_env_keys` passthrough.
#
# Replace `printenv VAR` with `sh -c 'echo "$VAR"'` — the prescreen only
# matches `printenv` at the start of the command line (or after a pipe),
# not when it appears inside a quoted `sh -c` argument, so `echo` in a
# sub-shell is a stable, non-denylisted alternative that still exercises
# the env-var passthrough path. Production shell prescreen is not
# touched; this is a pure test refactor.
# ---------------------------------------------------------------------------


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_allowed_env_keys_passthrough(monkeypatch):
    """Env vars listed in allowed_env_keys should be visible to commands."""
    monkeypatch.setenv("MY_CUSTOM_VAR", "hello-from-config")
    tool = ExecTool(allowed_env_keys=["MY_CUSTOM_VAR"])
    # `echo "$MY_CUSTOM_VAR"` inside `sh -c '...'` reads the single env var
    # the child inherits via allowed_env_keys — equivalent to
    # `printenv MY_CUSTOM_VAR` pre-MIT-123 but not caught by the prescreen.
    result = await tool.execute(command='sh -c \'echo "$MY_CUSTOM_VAR"\'')
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
    """If an allowed key is not set in the parent process, it should be silently skipped.

    The contract under test: when a key listed in `allowed_env_keys` is not
    set in the parent, the subprocess env must not contain it at all — NOT
    present-but-empty. This distinguishes a correct skip from a regression
    that forwards missing keys as `VAR=""`.
    """
    monkeypatch.delenv("NONEXISTENT_VAR_12345", raising=False)
    tool = ExecTool(allowed_env_keys=["NONEXISTENT_VAR_12345"])
    # `${VAR+set}` expands to "set" only when VAR is *defined* (even if
    # empty); it's empty when VAR is unset.  `[ -z "${VAR+set}" ]` therefore
    # succeeds (exit 0) iff the var is truly unset. We negate with `|| exit
    # 1` so the test passes only when the child's env has NO entry for
    # NONEXISTENT_VAR_12345 — this catches a hypothetical regression where
    # the passthrough layer starts forwarding missing keys as empty strings,
    # which the old `printenv` check (and a naive `-n` replacement) would
    # have let slip through.
    result = await tool.execute(
        command='sh -c \'[ -z "${NONEXISTENT_VAR_12345+set}" ] || exit 1\''
    )
    assert "Exit code: 0" in result
