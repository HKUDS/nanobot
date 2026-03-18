"""Test hook preloading and validation at startup."""

import tempfile
from pathlib import Path

from nanobot.agent.context import ContextBuilder


def test_preload_hooks_with_valid_config():
    """Test preload_hooks with valid configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "test-hook",
      "event": "PreToolUse",
      "command": "echo test"
    }
  ]
}
""")

        context = ContextBuilder(workspace)
        # Should not raise any exceptions
        context.preload_hooks()


def test_preload_hooks_with_invalid_config():
    """Test preload_hooks with invalid configuration (should log errors but not crash)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "invalid-hook",
      "event": "InvalidEvent",
      "command": "echo test"
    }
  ]
}
""")

        context = ContextBuilder(workspace)
        # Should not raise exceptions, just log errors
        context.preload_hooks()


def test_preload_hooks_with_missing_file():
    """Test preload_hooks when hooks.json doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        context = ContextBuilder(workspace)
        # Should not raise any exceptions
        context.preload_hooks()


def test_preload_hooks_with_malformed_json():
    """Test preload_hooks with malformed JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("{ invalid json }")

        context = ContextBuilder(workspace)
        # Should not raise exceptions, just log errors
        context.preload_hooks()


def test_preload_hooks_validates_all_fields():
    """Test that preload validates all hook configuration fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "hook1",
      "event": "PreToolUse",
      "command": "echo test",
      "priority": "not-an-int",
      "matcher": "[invalid(regex"
    }
  ]
}
""")

        context = ContextBuilder(workspace)
        # Should not crash despite multiple validation errors
        context.preload_hooks()
