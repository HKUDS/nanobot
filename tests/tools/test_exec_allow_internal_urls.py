"""Tests for exec tool allow_internal_urls configuration."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from nanobot.agent.tools.shell import ExecTool


def _fake_resolve_private(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_localhost(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


@pytest.mark.asyncio
async def test_exec_blocks_internal_urls_by_default():
    """By default, internal URLs should be blocked."""
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(
            command='curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/'
        )
    assert "Error" in result
    assert "internal" in result.lower() or "private" in result.lower()


@pytest.mark.asyncio
async def test_exec_allows_internal_urls_when_configured():
    """When allow_internal_urls is True, internal URLs should be allowed."""
    tool = ExecTool(allow_internal_urls=True)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        # The command should not be blocked by internal URL check, but might fail for other reasons
        guard_result = tool._guard_command(
            'curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/', 
            "/tmp"
        )
    # Should not be blocked by internal URL check
    assert guard_result is None or "internal" not in guard_result.lower()


@pytest.mark.asyncio
async def test_exec_still_blocks_dangerous_patterns_with_allow_internal_urls():
    """Dangerous patterns should still be blocked even with allow_internal_urls=True."""
    tool = ExecTool(allow_internal_urls=True)
    # This should still be blocked due to dangerous pattern
    guard_result = tool._guard_command("rm -rf /", "/tmp")
    assert guard_result is not None
    assert "dangerous pattern" in guard_result


@pytest.mark.asyncio
async def test_exec_guard_command_allows_internal_urls():
    """Test that _guard_command respects allow_internal_urls flag."""
    # With default setting (False), should block
    tool1 = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_localhost):
        guard_result1 = tool1._guard_command("curl http://localhost:8080/", "/tmp")
    assert guard_result1 is not None
    assert "internal" in guard_result1.lower()

    # With allow_internal_urls=True, should not block
    tool2 = ExecTool(allow_internal_urls=True)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_localhost):
        guard_result2 = tool2._guard_command("curl http://localhost:8080/", "/tmp")
    # Should not be blocked by internal URL check, might be None or some other validation
    assert guard_result2 is None or "internal" not in guard_result2.lower()