"""Tests for exec tool security — now via ToolGuard system.

The security checks that previously lived inside ExecTool._guard_command()
have been moved to pluggable guards.  These tests verify the guards work
correctly when wired through the ToolRegistry.
"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import patch

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.security.guards import NetworkGuard, PatternGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_resolve_private(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_localhost(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def _build_guarded_registry() -> ToolRegistry:
    """Build a registry with exec tool and standard guards."""
    reg = ToolRegistry()
    reg.register(ExecTool(timeout=5))
    reg.add_guard(PatternGuard())
    reg.add_guard(NetworkGuard())
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exec_blocks_curl_metadata():
    reg = _build_guarded_registry()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await reg.execute(
            "exec",
            {"command": 'curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/'},
        )
    assert "Error" in result
    assert "internal" in result.lower() or "private" in result.lower()


@pytest.mark.asyncio
async def test_exec_blocks_wget_localhost():
    reg = _build_guarded_registry()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_localhost):
        result = await reg.execute(
            "exec",
            {"command": "wget http://localhost:8080/secret -O /tmp/out"},
        )
    assert "Error" in result


@pytest.mark.asyncio
async def test_exec_allows_normal_commands():
    reg = _build_guarded_registry()
    result = await reg.execute("exec", {"command": "echo hello"})
    assert "hello" in result
    assert "Error" not in result.split("\n")[0]


@pytest.mark.asyncio
async def test_exec_allows_curl_to_public_url():
    """Commands with public URLs should not be blocked by the internal URL check."""
    reg = _build_guarded_registry()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        result = await reg.execute("exec", {"command": "curl https://example.com/api"})
    # Should not be blocked — either succeeds or fails due to no network, not a guard error
    assert "internal" not in result.lower()
    assert "private" not in result.lower()


@pytest.mark.asyncio
async def test_exec_blocks_chained_internal_url():
    """Internal URLs buried in chained commands should still be caught."""
    reg = _build_guarded_registry()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await reg.execute(
            "exec",
            {"command": "echo start && curl http://169.254.169.254/latest/meta-data/ && echo done"},
        )
    assert "Error" in result
