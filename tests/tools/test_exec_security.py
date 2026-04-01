"""Tests for exec tool internal URL blocking."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from nanobot.agent.tools.shell import ExecTool


def _fake_resolve_private(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_localhost(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


@pytest.mark.asyncio
async def test_exec_blocks_curl_metadata():
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(
            command='curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/'
        )
    assert "Error" in result
    assert "internal" in result.lower() or "private" in result.lower()


@pytest.mark.asyncio
async def test_exec_blocks_wget_localhost():
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_localhost):
        result = await tool.execute(command="wget http://localhost:8080/secret -O /tmp/out")
    assert "Error" in result


@pytest.mark.asyncio
async def test_exec_allows_normal_commands():
    tool = ExecTool(timeout=5)
    result = await tool.execute(command="echo hello")
    assert "hello" in result
    assert "Error" not in result.split("\n")[0]


@pytest.mark.asyncio
async def test_exec_allows_curl_to_public_url():
    """Commands with public URLs should not be blocked by the internal URL check."""
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        guard_result = tool._guard_command("curl https://example.com/api", "/tmp")
    assert guard_result is None


@pytest.mark.asyncio
async def test_exec_blocks_chained_internal_url():
    """Internal URLs buried in chained commands should still be caught."""
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(
            command="echo start && curl http://169.254.169.254/latest/meta-data/ && echo done"
        )
    assert "Error" in result


# --- allow_patterns whitelist tests ---

HOMER_ALLOW = [r"^/opt/homer/\.venv/bin/python /opt/homer/tools/\w+\.py(\s|$)"]


@pytest.mark.asyncio
async def test_allowlist_permits_approved_script():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/gmail_fetch.py --hours 24", "/tmp"
    )
    assert guard is None


@pytest.mark.asyncio
async def test_allowlist_permits_script_no_args():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py", "/tmp"
    )
    assert guard is None


@pytest.mark.asyncio
async def test_allowlist_blocks_cat_config():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("cat ~/.nanobot/config.json", "/tmp")
    assert guard is not None
    assert "allowlist" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_cat_secrets():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("cat /opt/homer/secrets/.env", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_arbitrary_python():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("python3 -c 'import os; print(os.environ)'", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_ls():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("ls /opt/homer/secrets/", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_grep():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("grep -r API_KEY /opt/homer/", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_sed_production_patch():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "sed -i 's/old/new/' /opt/homer/tools/context_updater.py", "/tmp"
    )
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_curl():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("curl https://example.com", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_pipe_after_approved_script():
    """Chaining a pipe after an approved script should still be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py | cat ~/.nanobot/config.json", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_ampersand_chain():
    """Chaining && after an approved script should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py && cat /etc/passwd", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_semicolon_chain():
    """Chaining ; after an approved script should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py ; cat secrets", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_backtick_injection():
    """Backtick command substitution should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py `cat secrets`", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_dollar_paren_injection():
    """$() command substitution should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py $(cat secrets)", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_no_allowlist_permits_everything():
    """Without allow_patterns, all non-dangerous commands pass."""
    tool = ExecTool(allow_patterns=None)
    guard = tool._guard_command("cat /etc/passwd", "/tmp")
    assert guard is None


@pytest.mark.asyncio
async def test_allowlist_blocks_newline_injection():
    """Newline injection to run a second command should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py\ncat ~/.nanobot/config.json", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_echo():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("echo hello", "/tmp")
    assert guard is not None
