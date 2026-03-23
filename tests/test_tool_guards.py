"""Tests for the pluggable ToolGuard system (nanobot.security.guards)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.security.guards import (
    BwrapGuard,
    DeniedPathsGuard,
    GuardContext,
    GuardResult,
    NetworkGuard,
    PatternGuard,
    ToolGuard,
    WorkspaceGuard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class EchoTool(Tool):
    """Minimal tool for testing guards without side effects."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo params"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, text: str = "", **kw: Any) -> str:
        return text


class FakeExecTool(Tool):
    """Exec-like tool name so guards with tool_names=['exec'] apply."""

    def __init__(self):
        self.working_dir = "/tmp"

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "fake exec"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    async def execute(self, command: str = "", **kw: Any) -> str:
        return f"executed: {command}"


class AlwaysBlockGuard(ToolGuard):
    """Guard that blocks everything — for testing."""

    def check(self, ctx: GuardContext) -> GuardResult:
        return GuardResult.block("always blocked")


class AlwaysPassGuard(ToolGuard):
    """Guard that passes everything — for testing."""

    def check(self, ctx: GuardContext) -> GuardResult:
        return GuardResult.ok()


# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------

def test_guard_result_ok():
    r = GuardResult.ok()
    assert r.allowed is True
    assert r.reason == ""


def test_guard_result_block():
    r = GuardResult.block("nope")
    assert r.allowed is False
    assert r.reason == "nope"


# ---------------------------------------------------------------------------
# ToolGuard ABC — applies_to
# ---------------------------------------------------------------------------

def test_guard_applies_to_all_by_default():
    guard = AlwaysPassGuard()
    assert guard.applies_to("exec")
    assert guard.applies_to("read_file")
    assert guard.applies_to("anything")


def test_guard_applies_to_specific_tools():
    guard = PatternGuard()
    assert guard.applies_to("exec")
    assert not guard.applies_to("read_file")


# ---------------------------------------------------------------------------
# DeniedPathsGuard
# ---------------------------------------------------------------------------

class TestDeniedPathsGuard:

    def test_blocks_exact_file(self, tmp_path):
        config = tmp_path / ".nanobot" / "config.json"
        config.parent.mkdir()
        config.write_text("{}")
        guard = DeniedPathsGuard([config])

        ctx = GuardContext(tool_name="read_file", params={"path": str(config)})
        result = guard.check(ctx)
        assert not result.allowed
        assert "protected" in result.reason.lower()

    def test_blocks_file_inside_denied_dir(self, tmp_path):
        config_dir = tmp_path / ".nanobot"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{}")
        guard = DeniedPathsGuard([config_dir])

        ctx = GuardContext(
            tool_name="read_file",
            params={"path": str(config_dir / "config.json")},
        )
        result = guard.check(ctx)
        assert not result.allowed

    def test_allows_normal_file(self, tmp_path):
        config = tmp_path / ".nanobot" / "config.json"
        guard = DeniedPathsGuard([config])

        normal = tmp_path / "readme.md"
        ctx = GuardContext(tool_name="read_file", params={"path": str(normal)})
        result = guard.check(ctx)
        assert result.allowed

    def test_does_not_apply_to_exec(self, tmp_path):
        config = tmp_path / ".nanobot" / "config.json"
        guard = DeniedPathsGuard([config])
        assert not guard.applies_to("exec")


# ---------------------------------------------------------------------------
# PatternGuard
# ---------------------------------------------------------------------------

class TestPatternGuard:

    def test_blocks_rm_rf(self):
        guard = PatternGuard()
        ctx = GuardContext(tool_name="exec", params={"command": "rm -rf /"})
        result = guard.check(ctx)
        assert not result.allowed
        assert "dangerous pattern" in result.reason.lower()

    def test_blocks_fork_bomb(self):
        guard = PatternGuard()
        ctx = GuardContext(tool_name="exec", params={"command": ":(){ :|:& };:"})
        result = guard.check(ctx)
        assert not result.allowed

    def test_allows_normal_command(self):
        guard = PatternGuard()
        ctx = GuardContext(tool_name="exec", params={"command": "echo hello"})
        result = guard.check(ctx)
        assert result.allowed

    def test_custom_deny_patterns(self):
        guard = PatternGuard(deny_patterns=[r"\bfoo\b"])
        ctx = GuardContext(tool_name="exec", params={"command": "foo bar"})
        result = guard.check(ctx)
        assert not result.allowed

    def test_allow_patterns_blocks_unlisted(self):
        guard = PatternGuard(deny_patterns=[], allow_patterns=[r"\bls\b"])
        ctx = GuardContext(tool_name="exec", params={"command": "echo hello"})
        result = guard.check(ctx)
        assert not result.allowed

    def test_allow_patterns_permits_listed(self):
        guard = PatternGuard(deny_patterns=[], allow_patterns=[r"\bls\b"])
        ctx = GuardContext(tool_name="exec", params={"command": "ls -la"})
        result = guard.check(ctx)
        assert result.allowed


# ---------------------------------------------------------------------------
# NetworkGuard
# ---------------------------------------------------------------------------

class TestNetworkGuard:

    def test_blocks_internal_url(self):
        import socket
        from unittest.mock import patch

        guard = NetworkGuard()

        def _resolve_private(hostname, port, family=0, type_=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]

        ctx = GuardContext(
            tool_name="exec",
            params={"command": "curl http://169.254.169.254/metadata"},
        )
        with patch("nanobot.security.network.socket.getaddrinfo", _resolve_private):
            result = guard.check(ctx)
        assert not result.allowed
        assert "internal" in result.reason.lower() or "private" in result.reason.lower()

    def test_allows_normal_command(self):
        guard = NetworkGuard()
        ctx = GuardContext(tool_name="exec", params={"command": "echo hello"})
        result = guard.check(ctx)
        assert result.allowed


# ---------------------------------------------------------------------------
# WorkspaceGuard
# ---------------------------------------------------------------------------

class TestWorkspaceGuard:

    def test_blocks_path_traversal(self, tmp_path):
        guard = WorkspaceGuard(tmp_path)
        ctx = GuardContext(
            tool_name="exec",
            params={"command": "cat ../../../etc/passwd"},
            working_dir=str(tmp_path),
        )
        result = guard.check(ctx)
        assert not result.allowed
        assert "path traversal" in result.reason.lower()

    def test_allows_normal_command(self, tmp_path):
        guard = WorkspaceGuard(tmp_path)
        ctx = GuardContext(
            tool_name="exec",
            params={"command": "echo hello"},
            working_dir=str(tmp_path),
        )
        result = guard.check(ctx)
        assert result.allowed


# ---------------------------------------------------------------------------
# BwrapGuard
# ---------------------------------------------------------------------------

class TestBwrapGuard:

    def test_available_property(self):
        import shutil
        guard = BwrapGuard()
        # On macOS/CI, bwrap is typically not available
        expected = shutil.which("bwrap") is not None
        assert guard.available == expected

    def test_check_always_allows(self):
        guard = BwrapGuard()
        ctx = GuardContext(tool_name="exec", params={"command": "echo test"})
        result = guard.check(ctx)
        assert result.allowed

    def test_transform_without_bwrap_passes_through(self, tmp_path):
        guard = BwrapGuard(hidden_paths=[tmp_path / ".nanobot"])
        guard._bwrap_path = None  # Force unavailable
        ctx = GuardContext(tool_name="exec", params={"command": "echo test"})
        transformed = guard.transform(ctx)
        assert transformed.params["command"] == "echo test"

    def test_transform_with_bwrap_rewrites_command(self, tmp_path):
        guard = BwrapGuard(
            hidden_paths=[tmp_path / ".nanobot"],
            workspace=tmp_path,
        )
        guard._bwrap_path = "/usr/bin/bwrap"  # Force available
        ctx = GuardContext(
            tool_name="exec",
            params={"command": "cat secret.txt"},
            working_dir=str(tmp_path),
        )
        transformed = guard.transform(ctx)
        cmd = transformed.params["command"]
        assert "/usr/bin/bwrap" in cmd
        assert "--tmpfs" in cmd
        assert "--unshare-all" in cmd
        assert "cat secret.txt" in cmd


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryGuards:

    @pytest.mark.asyncio
    async def test_guard_blocks_tool_execution(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.add_guard(AlwaysBlockGuard())

        result = await reg.execute("echo", {"text": "hello"})
        assert "Error" in result
        assert "always blocked" in result

    @pytest.mark.asyncio
    async def test_guard_allows_tool_execution(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.add_guard(AlwaysPassGuard())

        result = await reg.execute("echo", {"text": "hello"})
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_multiple_guards_first_block_wins(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.add_guard(AlwaysPassGuard())
        reg.add_guard(AlwaysBlockGuard())

        result = await reg.execute("echo", {"text": "hello"})
        assert "always blocked" in result

    @pytest.mark.asyncio
    async def test_guard_applies_to_filtering(self):
        """Guards with tool_names should only affect matching tools."""
        reg = ToolRegistry()
        reg.register(EchoTool())
        # PatternGuard only applies to "exec", not "echo"
        reg.add_guard(PatternGuard())

        result = await reg.execute("echo", {"text": "rm -rf /"})
        # Should succeed because PatternGuard doesn't apply to "echo"
        assert result == "rm -rf /"

    @pytest.mark.asyncio
    async def test_denied_paths_guard_in_registry(self, tmp_path):
        """DeniedPathsGuard should block read_file through registry."""
        from nanobot.agent.tools.filesystem import ReadFileTool

        config = tmp_path / ".nanobot" / "config.json"
        config.parent.mkdir()
        config.write_text('{"secret": "key"}')

        reg = ToolRegistry()
        reg.register(ReadFileTool(workspace=tmp_path))
        reg.add_guard(DeniedPathsGuard([config, config.parent]))

        result = await reg.execute("read_file", {"path": str(config)})
        assert "Error" in result
        assert "protected" in result.lower()

    @pytest.mark.asyncio
    async def test_pattern_guard_blocks_exec_in_registry(self):
        reg = ToolRegistry()
        reg.register(FakeExecTool())
        reg.add_guard(PatternGuard())

        result = await reg.execute("exec", {"command": "rm -rf /"})
        assert "Error" in result
        assert "dangerous pattern" in result.lower()

    @pytest.mark.asyncio
    async def test_pattern_guard_allows_normal_exec(self):
        reg = ToolRegistry()
        reg.register(FakeExecTool())
        reg.add_guard(PatternGuard())

        result = await reg.execute("exec", {"command": "echo hello"})
        assert result == "executed: echo hello"

    def test_add_and_remove_guard(self):
        reg = ToolRegistry()
        guard = AlwaysBlockGuard()
        reg.add_guard(guard)
        assert len(reg.guards) == 1
        reg.remove_guard(guard)
        assert len(reg.guards) == 0

    def test_remove_nonexistent_guard_is_noop(self):
        reg = ToolRegistry()
        guard = AlwaysBlockGuard()
        reg.remove_guard(guard)  # Should not raise
        assert len(reg.guards) == 0


# ---------------------------------------------------------------------------
# Custom guard (demonstrates extensibility)
# ---------------------------------------------------------------------------

class MaxCommandLengthGuard(ToolGuard):
    """Example custom guard: blocks commands longer than N chars."""

    tool_names = ["exec"]

    def __init__(self, max_length: int = 1000):
        self._max = max_length

    def check(self, ctx: GuardContext) -> GuardResult:
        cmd = ctx.params.get("command", "")
        if len(cmd) > self._max:
            return GuardResult.block(
                f"Command too long ({len(cmd)} chars, max {self._max})"
            )
        return GuardResult.ok()


class TestCustomGuard:

    @pytest.mark.asyncio
    async def test_custom_guard_blocks_long_command(self):
        reg = ToolRegistry()
        reg.register(FakeExecTool())
        reg.add_guard(MaxCommandLengthGuard(max_length=10))

        result = await reg.execute("exec", {"command": "echo " + "x" * 100})
        assert "Error" in result
        assert "too long" in result.lower()

    @pytest.mark.asyncio
    async def test_custom_guard_allows_short_command(self):
        reg = ToolRegistry()
        reg.register(FakeExecTool())
        reg.add_guard(MaxCommandLengthGuard(max_length=100))

        result = await reg.execute("exec", {"command": "echo hello"})
        assert result == "executed: echo hello"
