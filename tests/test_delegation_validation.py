"""Tests for Phase D: delegation role validation.

Verifies that DelegateTool and DelegateParallelTool reject unknown
target_role values with clear error messages before dispatching.
"""

from __future__ import annotations

from nanobot.errors import UnknownRoleError
from nanobot.tools.builtin.delegate import (
    DelegateParallelTool,
    DelegateTool,
    DelegationResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AVAILABLE_ROLES = ["coder", "researcher", "general"]


def _roles_fn() -> list[str]:
    return list(_AVAILABLE_ROLES)


async def _fake_dispatch(
    target_role: str,
    task: str,
    context: str | None,
) -> DelegationResult:
    return DelegationResult(content=f"Done by {target_role or 'auto'}", tools_used=["exec"])


def _make_delegate_tool(
    *,
    with_dispatch: bool = True,
    with_roles: bool = True,
) -> DelegateTool:
    tool = DelegateTool()
    if with_dispatch:
        tool.set_dispatch(_fake_dispatch)
    if with_roles:
        tool.set_available_roles_fn(_roles_fn)
    return tool


def _make_parallel_tool(
    *,
    with_dispatch: bool = True,
    with_roles: bool = True,
) -> DelegateParallelTool:
    tool = DelegateParallelTool()
    if with_dispatch:
        tool.set_dispatch(_fake_dispatch)
    if with_roles:
        tool.set_available_roles_fn(_roles_fn)
    return tool


# ---------------------------------------------------------------------------
# UnknownRoleError
# ---------------------------------------------------------------------------


class TestUnknownRoleError:
    def test_error_message_with_available(self) -> None:
        err = UnknownRoleError("web", available=["coder", "researcher"])
        assert "web" in str(err)
        assert "coder" in str(err)
        assert "researcher" in str(err)
        assert err.role_name == "web"
        assert err.available_roles == ["coder", "researcher"]
        assert err.error_type == "unknown_role"
        assert err.recoverable is True

    def test_error_message_empty_available(self) -> None:
        err = UnknownRoleError("unknown")
        assert "none configured" in str(err)

    def test_inherits_tool_execution_error(self) -> None:
        from nanobot.errors import ToolExecutionError

        err = UnknownRoleError("bad")
        assert isinstance(err, ToolExecutionError)
        assert err.tool_name == "delegate"


# ---------------------------------------------------------------------------
# DelegateTool role validation
# ---------------------------------------------------------------------------


class TestDelegateToolValidation:
    async def test_unknown_role_rejected(self) -> None:
        tool = _make_delegate_tool()
        result = await tool.execute(task="do work", target_role="web")
        assert not result.success
        assert result.metadata.get("error_type") == "unknown_role"
        assert "web" in result.output
        assert "coder" in result.output
        assert "researcher" in result.output

    async def test_known_role_accepted(self) -> None:
        tool = _make_delegate_tool()
        result = await tool.execute(task="write code", target_role="coder")
        assert result.success
        assert "Done by coder" in result.output

    async def test_empty_role_allowed(self) -> None:
        """Empty target_role skips validation — coordinator classifies."""
        tool = _make_delegate_tool()
        result = await tool.execute(task="classify me", target_role="")
        assert result.success
        assert "Done by auto" in result.output

    async def test_whitespace_role_treated_as_empty(self) -> None:
        tool = _make_delegate_tool()
        result = await tool.execute(task="do work", target_role="   ")
        assert result.success

    async def test_no_roles_fn_skips_validation(self) -> None:
        """When roles callback is not set, validation is skipped."""
        tool = _make_delegate_tool(with_roles=False)
        result = await tool.execute(task="do work", target_role="anything")
        assert result.success

    async def test_no_dispatch_returns_config_error(self) -> None:
        tool = _make_delegate_tool(with_dispatch=False)
        result = await tool.execute(task="test", target_role="coder")
        assert not result.success
        assert result.metadata.get("error_type") == "config"

    async def test_empty_available_roles_skips_validation(self) -> None:
        """If the roles callback returns [], don't reject (no roles configured yet)."""
        tool = DelegateTool()
        tool.set_dispatch(_fake_dispatch)
        tool.set_available_roles_fn(lambda: [])
        result = await tool.execute(task="work", target_role="anything")
        assert result.success


# ---------------------------------------------------------------------------
# DelegateParallelTool role validation
# ---------------------------------------------------------------------------


class TestDelegateParallelToolValidation:
    async def test_unknown_role_in_subtask_rejected(self) -> None:
        tool = _make_parallel_tool()
        result = await tool.execute(
            subtasks=[
                {"task": "find info", "target_role": "researcher"},
                {"task": "open youtube", "target_role": "web"},
            ]
        )
        assert not result.success
        assert result.metadata.get("error_type") == "unknown_role"
        assert "web" in result.output
        assert "Available roles" in result.output

    async def test_multiple_unknown_roles_all_reported(self) -> None:
        tool = _make_parallel_tool()
        result = await tool.execute(
            subtasks=[
                {"task": "a", "target_role": "web"},
                {"task": "b", "target_role": "coder"},
                {"task": "c", "target_role": "browser"},
            ]
        )
        assert not result.success
        assert "web" in result.output
        assert "browser" in result.output
        # Valid role "coder" should NOT appear as invalid
        assert "Subtask [2]" not in result.output

    async def test_all_valid_roles_accepted(self) -> None:
        tool = _make_parallel_tool()
        result = await tool.execute(
            subtasks=[
                {"task": "code", "target_role": "coder"},
                {"task": "research", "target_role": "researcher"},
            ]
        )
        assert result.success

    async def test_empty_roles_in_subtasks_allowed(self) -> None:
        tool = _make_parallel_tool()
        result = await tool.execute(
            subtasks=[
                {"task": "auto-route this"},
                {"task": "also auto-route", "target_role": ""},
            ]
        )
        assert result.success

    async def test_no_roles_fn_skips_validation(self) -> None:
        tool = _make_parallel_tool(with_roles=False)
        result = await tool.execute(subtasks=[{"task": "work", "target_role": "bogus"}])
        assert result.success

    async def test_no_dispatch_blocked(self) -> None:
        tool = _make_parallel_tool(with_dispatch=False)
        result = await tool.execute(subtasks=[{"task": "work"}])
        assert not result.success
