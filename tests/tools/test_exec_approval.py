"""Tests for exec tool approval mechanism."""

from __future__ import annotations

import pytest

from nanobot.agent.tools.shell import ApprovalRule, ExecTool, ExecToolConfig


# ---------------------------------------------------------------------------
# ApprovalRule model
# ---------------------------------------------------------------------------


def test_approval_rule_default_policy_is_ask():
    """Default policy should be 'ask'."""
    rule = ApprovalRule(pattern=r"rm\s+-rf")
    assert rule.policy == "ask"


def test_approval_rule_explicit_policy():
    """Explicitly set policy should be preserved."""
    rule = ApprovalRule(pattern=r"git\s+push", policy="auto")
    assert rule.policy == "auto"


def test_approval_rule_invalid_policy_raises_error():
    """Invalid policy should raise validation error."""
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as excinfo:
        ApprovalRule(pattern=r"rm\s+-rf", policy="invalid")
    
    assert "Invalid policy: invalid, must be one of auto/ask/deny" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ExecToolConfig new fields
# ---------------------------------------------------------------------------


def test_exec_tool_config_defaults():
    """New config fields should have sensible defaults."""
    cfg = ExecToolConfig()
    assert cfg.enable_user_confirmation is False
    assert cfg.safe_binaries == []
    assert cfg.approval_rules == []


def test_exec_tool_config_with_new_fields():
    """Config should accept the new fields."""
    cfg = ExecToolConfig(
        enable_user_confirmation=True,
        safe_binaries=["git"],
        approval_rules=[ApprovalRule(pattern=r"rm\s+-rf", policy="ask")],
    )
    assert cfg.enable_user_confirmation is True
    assert cfg.safe_binaries == ["git"]
    assert len(cfg.approval_rules) == 1


# ---------------------------------------------------------------------------
# _match_approval_policy
# ---------------------------------------------------------------------------


def test_safe_binaries_are_auto_approved():
    """Commands using safe binaries should be auto-approved."""
    tool = ExecTool(
        enable_user_confirmation=True,
        safe_binaries=["git", "python3"],
    )
    assert tool._match_approval_policy("git status") == "auto"
    assert tool._match_approval_policy("python3 script.py") == "auto"


def test_safe_binaries_no_match():
    """Commands not using safe binaries should return None."""
    tool = ExecTool(safe_binaries=["git", "python3"])
    assert tool._match_approval_policy("rm -rf /tmp") is None


def test_safe_binaries_strips_path_prefix():
    """Safe binary matching should strip path prefixes."""
    tool = ExecTool(safe_binaries=["git"])
    assert tool._match_approval_policy("/usr/bin/git status") == "auto"


def test_safe_binaries_empty_command():
    """Empty command should not match any safe binary."""
    tool = ExecTool(safe_binaries=["git"])
    assert tool._match_approval_policy("") is None


def test_approval_rules_are_processed_in_order():
    """Rules should be matched in order, first match wins."""
    tool = ExecTool(
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf\s+/tmp/build", policy="auto"),
            ApprovalRule(pattern=r"rm\s+-rf", policy="ask"),
        ],
    )
    assert tool._match_approval_policy("rm -rf /tmp/build") == "auto"
    assert tool._match_approval_policy("rm -rf /tmp/other") == "ask"


def test_approval_rules_take_priority_over_safe_binaries():
    """Approval rules should be checked before safe_binaries."""
    tool = ExecTool(
        safe_binaries=["git"],
        approval_rules=[
            ApprovalRule(pattern=r"git\s+push", policy="ask"),
        ],
    )
    assert tool._match_approval_policy("git push") == "ask"
    assert tool._match_approval_policy("git status") == "auto"


def test_no_approval_rules_no_safe_binaries():
    """With no rules and no safe_binaries, policy should be None."""
    tool = ExecTool()
    assert tool._match_approval_policy("git status") is None


# ---------------------------------------------------------------------------
# _check_user_confirmation
# ---------------------------------------------------------------------------


def test_user_confirmation_keywords_recognized():
    """Various confirmation keywords should be recognized."""
    assert ExecTool._check_user_confirmation("yes") is True
    assert ExecTool._check_user_confirmation("y") is True
    assert ExecTool._check_user_confirmation("ok") is True
    assert ExecTool._check_user_confirmation("approve") is True
    assert ExecTool._check_user_confirmation("同意") is True
    assert ExecTool._check_user_confirmation("是的，执行吧") is True


def test_user_confirmation_rejects_negative():
    """Negative responses should not be confirmed."""
    assert ExecTool._check_user_confirmation("no") is False
    assert ExecTool._check_user_confirmation("cancel") is False
    assert ExecTool._check_user_confirmation("deny") is False
    assert ExecTool._check_user_confirmation("拒绝") is False


def test_user_confirmation_case_insensitive():
    """Confirmation should be case-insensitive."""
    assert ExecTool._check_user_confirmation("Yes") is True
    assert ExecTool._check_user_confirmation("YES") is True
    assert ExecTool._check_user_confirmation("OK") is True


def test_user_confirmation_empty_string():
    """Empty string should not be confirmed."""
    assert ExecTool._check_user_confirmation("") is False


# ---------------------------------------------------------------------------
# _guard_command — approval rules
# ---------------------------------------------------------------------------


def test_guard_command_without_confirmation_blocks_deny():
    """Without confirmation enabled, deny patterns block directly."""
    tool = ExecTool(enable_user_confirmation=False)
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is not None
    assert "deny pattern" in result.lower()


def test_guard_command_with_confirmation_still_returns_deny_error():
    """With confirmation enabled, _guard_command still returns deny error.

    The execute() method is responsible for converting this into a
    NEEDS_CONFIRMATION prompt.
    """
    tool = ExecTool(enable_user_confirmation=True)
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is not None
    assert "deny pattern" in result.lower()


def test_approval_rule_deny_works():
    """Policy 'deny' should block command regardless of enable_user_confirmation."""
    tool = ExecTool(
        enable_user_confirmation=True,
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf\s+/", policy="deny"),
        ],
    )
    result = tool._guard_command("rm -rf /", "/")
    assert result is not None
    assert "blocked by approval policy" in result.lower()


def test_approval_rule_auto_works():
    """Policy 'auto' should bypass safety checks for matching pattern."""
    tool = ExecTool()
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is not None

    tool = ExecTool(
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf\s+/tmp/build", policy="auto"),
        ],
    )
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is None


def test_approval_rule_ask_falls_through_to_deny():
    """Policy 'ask' should not bypass deny checks; the deny pattern still blocks."""
    tool = ExecTool(
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf", policy="ask"),
        ],
    )
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    # 'ask' doesn't auto-approve, so deny pattern still catches it
    assert result is not None
    assert "deny pattern" in result.lower()


def test_approval_rule_deny_overrides_enable_user_confirmation():
    """Even with enable_user_confirmation=True, 'deny' policy hard-blocks."""
    tool = ExecTool(
        enable_user_confirmation=True,
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf\s+/", policy="deny"),
        ],
    )
    result = tool._guard_command("rm -rf /", "/")
    assert "blocked by approval policy" in result.lower()
    assert "deny pattern" not in result.lower()


def test_disabled_confirmation_maintains_backward_compatibility():
    """When enable_user_confirmation is False, behavior is same as before."""
    tool = ExecTool(enable_user_confirmation=False)
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is not None
    assert "deny pattern" in result.lower()


# ---------------------------------------------------------------------------
# Pending command state
# ---------------------------------------------------------------------------


def test_pending_command_state_management():
    """Tool should correctly manage pending command state."""
    tool = ExecTool(enable_user_confirmation=True)
    assert tool._pending_command is None

    tool._pending_command = "rm -rf /tmp/build"
    tool._pending_cwd = "/tmp"
    tool._pending_timeout = 60

    assert tool._pending_command == "rm -rf /tmp/build"
    assert tool._pending_cwd == "/tmp"

    tool._pending_command = None
    tool._pending_cwd = None
    tool._pending_timeout = None

    assert tool._pending_command is None


# ---------------------------------------------------------------------------
# execute() — confirmation flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_with_confirmation_returns_needs_confirmation():
    """When confirmation is enabled, execute() returns NEEDS_CONFIRMATION prompt."""
    tool = ExecTool(enable_user_confirmation=True)
    result = await tool.execute("rm -rf /tmp/build")
    assert result.startswith("NEEDS_CONFIRMATION:")
    assert "rm -rf /tmp/build" in result
    assert tool._pending_command == "rm -rf /tmp/build"
    assert tool._pending_cwd is not None


@pytest.mark.asyncio
async def test_execute_without_confirmation_blocks_deny():
    """When confirmation is disabled, execute() returns hard block."""
    tool = ExecTool(enable_user_confirmation=False)
    result = await tool.execute("rm -rf /tmp/build")
    assert "deny pattern" in result.lower()
    assert tool._pending_command is None


@pytest.mark.asyncio
async def test_execute_confirmed_runs_pending_command():
    """With confirmed=True, execute() runs the pending command directly."""
    tool = ExecTool(enable_user_confirmation=True)
    await tool.execute("rm -rf /tmp/build")
    assert tool._pending_command is not None

    result = await tool.execute("rm -rf /tmp/build", confirmed=True)
    assert "deny pattern" not in result.lower()
    assert "NEEDS_CONFIRMATION" not in result
    assert tool._pending_command is None


@pytest.mark.asyncio
async def test_execute_confirmed_mismatch_falls_through():
    """If confirmed command doesn't match pending, fall through to guard."""
    tool = ExecTool(enable_user_confirmation=True)
    await tool.execute("rm -rf /tmp/build")
    assert tool._pending_command is not None

    result = await tool.execute("rm -rf /tmp/other", confirmed=True)
    # Pending was cleared; new command hits guard (either deny or NEEDS_CONFIRMATION)
    assert "deny pattern" in result.lower() or "NEEDS_CONFIRMATION" in result


@pytest.mark.asyncio
async def test_execute_confirmed_without_pending_falls_through():
    """confirmed=True with no pending command should fall through to normal guard."""
    tool = ExecTool(enable_user_confirmation=True)
    assert tool._pending_command is None

    result = await tool.execute("rm -rf /tmp/build", confirmed=True)
    # No pending command, so confirmed is ignored; hits normal guard
    assert "NEEDS_CONFIRMATION" in result or "deny pattern" in result.lower()


@pytest.mark.asyncio
async def test_execute_auto_approval_rule_bypasses_guard():
    """An 'auto' approval rule should allow denied commands to execute."""
    tool = ExecTool(
        enable_user_confirmation=True,
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf\s+/tmp/build", policy="auto"),
        ],
    )
    result = await tool.execute("rm -rf /tmp/build")
    assert "deny pattern" not in result.lower()
    assert "NEEDS_CONFIRMATION" not in result


@pytest.mark.asyncio
async def test_execute_deny_approval_rule_hard_blocks():
    """A 'deny' approval rule should hard-block even with confirmation enabled."""
    tool = ExecTool(
        enable_user_confirmation=True,
        approval_rules=[
            ApprovalRule(pattern=r"rm\s+-rf\s+/", policy="deny"),
        ],
    )
    result = await tool.execute("rm -rf /")
    assert "blocked by approval policy" in result.lower()
    assert "NEEDS_CONFIRMATION" not in result
    assert tool._pending_command is None


@pytest.mark.asyncio
async def test_execute_ssrf_not_converted_to_confirmation():
    """SSRF blocks should NOT be converted to NEEDS_CONFIRMATION."""
    tool = ExecTool(enable_user_confirmation=True)
    result = await tool.execute("curl http://127.0.0.1/admin")
    # SSRF is a hard policy boundary, not a deny pattern
    assert "NEEDS_CONFIRMATION" not in result
    assert "internal" in result.lower() or "private" in result.lower()


@pytest.mark.asyncio
async def test_execute_normal_command_unaffected():
    """Normal commands should execute without any confirmation prompt."""
    tool = ExecTool(enable_user_confirmation=True)
    result = await tool.execute("echo hello")
    assert "Exit code" in result
    assert "NEEDS_CONFIRMATION" not in result


@pytest.mark.asyncio
async def test_execute_safe_binary_bypasses_guard():
    """Commands using safe binaries should execute directly."""
    tool = ExecTool(
        enable_user_confirmation=True,
        safe_binaries=["echo"],
    )
    result = await tool.execute("echo hello")
    assert "Exit code" in result
    assert "NEEDS_CONFIRMATION" not in result
