"""Test JSON-based user-defined hooks."""

import tempfile
from pathlib import Path

from nanobot.agent.hooks import HookEvent, HookRegistry, load_hooks_from_json
from nanobot.agent.hooks.json_loader import validate_hook_config


def test_load_hooks_from_json():
    """Test loading hooks from JSON configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        # Create hooks.json
        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "test-hook",
      "event": "PreToolUse",
      "matcher": "^exec$",
      "command": "echo 'test'",
      "priority": 50
    }
  ]
}
""")

        hooks = load_hooks_from_json(workspace)
        assert len(hooks) == 1
        assert hooks[0].name == "test-hook"
        assert hooks[0].priority == 50
        assert hooks[0].matcher == "^exec$"


def test_load_hooks_missing_file():
    """Test loading hooks when file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks = load_hooks_from_json(workspace)
        assert len(hooks) == 0


def test_json_hook_blocks_on_exit_2():
    """Test that exit code 2 blocks execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        # Create a hook that always blocks
        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "blocker",
      "event": "PreToolUse",
      "command": "echo 'blocked' && exit 2"
    }
  ]
}
""")

        hooks = load_hooks_from_json(workspace)
        registry = HookRegistry()
        for hook in hooks:
            registry.register(hook)

        result = registry.emit(HookEvent.PRE_TOOL_USE, {
            "tool_name": "exec",
            "tool_args": {"command": "ls"}
        })

        assert not result.proceed
        assert "blocked" in result.reason


def test_json_hook_passes_on_exit_0():
    """Test that exit code 0 allows execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "passer",
      "event": "PreToolUse",
      "command": "exit 0"
    }
  ]
}
""")

        hooks = load_hooks_from_json(workspace)
        registry = HookRegistry()
        for hook in hooks:
            registry.register(hook)

        result = registry.emit(HookEvent.PRE_TOOL_USE, {
            "tool_name": "exec",
            "tool_args": {}
        })

        assert result.proceed


def test_json_hook_receives_env_vars():
    """Test that hook receives environment variables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        # Create a hook that checks for TOOL_NAME env var
        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "env-checker",
      "event": "PreToolUse",
      "command": "test \\"$TOOL_NAME\\" = \\"exec\\" && exit 0 || exit 2"
    }
  ]
}
""")

        hooks = load_hooks_from_json(workspace)
        registry = HookRegistry()
        for hook in hooks:
            registry.register(hook)

        # Should pass when TOOL_NAME=exec
        result = registry.emit(HookEvent.PRE_TOOL_USE, {
            "tool_name": "exec",
            "tool_args": {}
        })
        assert result.proceed

        # Should block when TOOL_NAME=other
        result2 = registry.emit(HookEvent.PRE_TOOL_USE, {
            "tool_name": "other",
            "tool_args": {}
        })
        assert not result2.proceed


def test_validate_hook_config_valid():
    """Test validation of valid hook configuration."""
    config = {
        "name": "test-hook",
        "event": "PreToolUse",
        "command": "echo test",
        "priority": 100,
        "matcher": "^exec$"
    }
    is_valid, error = validate_hook_config(config)
    assert is_valid
    assert error == ""


def test_validate_hook_config_missing_required_field():
    """Test validation fails when required field is missing."""
    config = {
        "name": "test-hook",
        "event": "PreToolUse"
        # missing "command"
    }
    is_valid, error = validate_hook_config(config)
    assert not is_valid
    assert "Missing required field: command" in error


def test_validate_hook_config_invalid_event():
    """Test validation fails with invalid event name."""
    config = {
        "name": "test-hook",
        "event": "InvalidEvent",
        "command": "echo test"
    }
    is_valid, error = validate_hook_config(config)
    assert not is_valid
    assert "Invalid event" in error


def test_validate_hook_config_invalid_priority():
    """Test validation fails with non-integer priority."""
    config = {
        "name": "test-hook",
        "event": "PreToolUse",
        "command": "echo test",
        "priority": "high"  # should be int
    }
    is_valid, error = validate_hook_config(config)
    assert not is_valid
    assert "Priority must be an integer" in error


def test_validate_hook_config_invalid_regex():
    """Test validation fails with invalid regex matcher."""
    config = {
        "name": "test-hook",
        "event": "PreToolUse",
        "command": "echo test",
        "matcher": "[invalid(regex"
    }
    is_valid, error = validate_hook_config(config)
    assert not is_valid
    assert "Invalid matcher regex" in error


def test_load_hooks_validate_only():
    """Test validate_only mode doesn't create hook instances."""
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

        # validate_only should return empty list
        hooks = load_hooks_from_json(workspace, validate_only=True)
        assert len(hooks) == 0


def test_load_hooks_with_validation_errors():
    """Test loading hooks with validation errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        hooks_dir = workspace / ".nanobot"
        hooks_dir.mkdir()

        hooks_file = hooks_dir / "hooks.json"
        hooks_file.write_text("""
{
  "hooks": [
    {
      "name": "valid-hook",
      "event": "PreToolUse",
      "command": "echo test"
    },
    {
      "name": "invalid-hook",
      "event": "InvalidEvent",
      "command": "echo test"
    }
  ]
}
""")

        # Should only load valid hooks
        hooks = load_hooks_from_json(workspace)
        assert len(hooks) == 1
        assert hooks[0].name == "valid-hook"
