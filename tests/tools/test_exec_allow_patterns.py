"""Tests for allow_patterns priority over deny_patterns."""

from __future__ import annotations

from nanobot.agent.tools.shell import ExecTool


def test_deny_patterns_block_rm_rf():
    """Baseline: rm -rf is blocked by default deny list."""
    tool = ExecTool()
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_allow_patterns_bypass_deny():
    """allow_patterns take priority: matching command skips deny check."""
    tool = ExecTool(allow_patterns=[r"rm\s+-rf\s+/tmp/.*"])
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is None


def test_allow_patterns_must_match_to_bypass():
    """Non-matching allow_patterns do NOT bypass deny."""
    tool = ExecTool(allow_patterns=[r"rm\s+-rf\s+/opt/"])
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_extra_deny_patterns_from_config():
    """User-supplied deny patterns are appended to built-in list."""
    tool = ExecTool(deny_patterns=[r"\bping\b"])
    # ping is blocked by extra deny
    assert tool._guard_command("ping example.com", "/tmp") is not None
    # rm -rf still blocked by built-in deny
    assert tool._guard_command("rm -rf /tmp/x", "/tmp") is not None


def test_allow_patterns_bypass_extra_deny():
    """allow_patterns also bypasses user-supplied deny patterns."""
    tool = ExecTool(
        deny_patterns=[r"\bping\b"],
        allow_patterns=[r"\bping\s+example\.com\b"],
    )
    result = tool._guard_command("ping example.com", "/tmp")
    assert result is None


def test_allow_patterns_is_whitelist_only():
    """When allow_patterns is set, non-matching non-denied commands are blocked."""
    tool = ExecTool(allow_patterns=[r"echo\s+hello"])
    # echo matches allow → ok
    assert tool._guard_command("echo hello", "/tmp") is None
    # ls does not match allow and is not in deny → blocked by allowlist
    result = tool._guard_command("ls /tmp", "/tmp")
    assert result is not None
    assert "allowlist" in result.lower()


def test_guard_allow_patterns_block_non_matching_chained_segment():
    """Every top-level shell segment must match an allow pattern."""
    tool = ExecTool(allow_patterns=[r"\becho\s+allowlisted\b"])

    result = tool._guard_command("echo allowlisted && touch /tmp/evil", "/tmp")
    assert result is not None
    assert "allowlist" in result.lower()


def test_deny_patterns_search_original_command_with_quoted_hash():
    """Deny checks must still inspect text after a quoted hash."""
    tool = ExecTool(deny_patterns=[r"\brm\s+-rf\s+/"])
    result = tool._guard_command('echo "#"; rm -rf /', "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_allow_patterns_fullmatch_allows_exact_command():
    """A full-command allow pattern can still exempt an exact denied command."""
    tool = ExecTool(allow_patterns=[r"rm\s+-rf\s+/tmp/build"])
    result = tool._guard_command("rm -rf /tmp/build", "/tmp")
    assert result is None


def test_guard_allow_patterns_allow_single_matching_segment():
    tool = ExecTool(allow_patterns=[r"\becho\s+allowlisted\b"])

    result = tool._guard_command("echo allowlisted", "/tmp")

    assert result is None


def test_guard_allow_patterns_allow_multiple_matching_segments():
    tool = ExecTool(
        allow_patterns=[
            r"\becho\s+allowlisted\b",
            r"\becho\s+also_allowed\b",
        ]
    )

    result = tool._guard_command("echo allowlisted && echo also_allowed", "/tmp")

    assert result is None


def test_guard_allow_patterns_keep_fullmatch_style_compatibility():
    tool = ExecTool(allow_patterns=[r"^echo\s+allowlisted$"])

    result = tool._guard_command("echo allowlisted", "/tmp")

    assert result is None
