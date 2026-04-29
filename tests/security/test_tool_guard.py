"""Tests for tool security guard."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.security.tool_guard import (
    AuditEntry,
    DenialReason,
    SecurityConfig,
    ToolSecurityGuard,
    _SENSITIVE_FILE_PATTERNS,
    configure_guard,
    get_default_guard,
)


class TestSecurityConfig:
    """Tests for SecurityConfig."""

    def test_default_values(self):
        """Default values should be disabled for backward compatibility."""
        config = SecurityConfig()
        assert config.enabled is False
        assert config.block_sensitive_files is True
        assert config.block_system_dirs is True
        assert config.block_path_traversal is True
        assert config.allowed_tools is None
        assert config.denied_tools is None
        assert config.additional_sensitive_patterns is None
        assert config.additional_blocked_paths is None
        assert config.audit_enabled is True


class TestToolSecurityGuard:
    """Tests for ToolSecurityGuard."""

    def test_guard_disabled_by_default(self):
        """Guard should be disabled by default for backward compatibility."""
        guard = ToolSecurityGuard()
        assert guard.enabled is False

    def test_guard_enabled_denies_sensitive_files(self, tmp_path):
        """When enabled, guard should deny access to sensitive files."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": "/home/user/.env"},
            workspace=tmp_path,
        )
        
        assert allowed is False
        assert error is not None
        assert "sensitive" in error.lower()
        assert audit is not None
        assert audit.reason == DenialReason.SENSITIVE_FILE

    def test_guard_disabled_allows_everything(self, tmp_path):
        """When disabled, guard should allow everything."""
        config = SecurityConfig(enabled=False)
        guard = ToolSecurityGuard(config)
        
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": "/home/user/.env"},
            workspace=tmp_path,
        )
        
        assert allowed is True
        assert error is None

    def test_tool_denylist(self):
        """Tools in denylist should be denied."""
        config = SecurityConfig(
            enabled=True,
            denied_tools=["exec", "write_file"],
        )
        guard = ToolSecurityGuard(config)
        
        allowed, error, _ = guard.check_tool("exec", {"command": "rm -rf /"}, workspace=Path("/tmp"))
        assert allowed is False
        assert "denied" in error.lower()

        allowed, error, _ = guard.check_tool("read_file", {"path": "/tmp/test.txt"}, workspace=Path("/tmp"))
        assert allowed is True

    def test_tool_allowlist(self):
        """Only tools in allowlist should be allowed."""
        config = SecurityConfig(
            enabled=True,
            allowed_tools=["read_file", "list_dir"],
        )
        guard = ToolSecurityGuard(config)
        
        allowed, error, _ = guard.check_tool("read_file", {"path": "/tmp/test.txt"}, workspace=Path("/tmp"))
        assert allowed is True

        allowed, error, _ = guard.check_tool("write_file", {"path": "/tmp/test.txt", "content": "test"}, workspace=Path("/tmp"))
        assert allowed is False
        assert "not allowed" in error.lower()

    def test_denylist_takes_precedence_over_allowlist(self):
        """Denylist should take precedence over allowlist."""
        config = SecurityConfig(
            enabled=True,
            allowed_tools=["read_file", "write_file"],
            denied_tools=["write_file"],
        )
        guard = ToolSecurityGuard(config)
        
        allowed, _, _ = guard.check_tool("read_file", {"path": "/tmp/test.txt"}, workspace=Path("/tmp"))
        assert allowed is True

        allowed, _, _ = guard.check_tool("write_file", {"path": "/tmp/test.txt", "content": "test"}, workspace=Path("/tmp"))
        assert allowed is False

    def test_system_directory_blocking(self):
        """System directories should be blocked."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        allowed, error, _ = guard.check_tool(
            "read_file",
            {"path": "/etc/passwd"},
            workspace=Path("/tmp"),
        )
        
        assert allowed is False
        assert "system" in error.lower() or "directory" in error.lower()

    @pytest.mark.parametrize("sensitive_path", [
        "/home/user/.env",
        "/home/user/.env.local",
        "/home/user/.ssh/id_rsa",
        "/home/user/.ssh/id_ecdsa",
        "/home/user/secrets.json",
        "/home/user/token.txt",
        "/home/user/api_key",
        "/home/user/private.key",
        "/home/user/.aws/credentials",
        "/home/user/.kube/config",
        "/home/user/.npmrc",
    ])
    def test_various_sensitive_file_patterns(self, sensitive_path):
        """Various sensitive file patterns should be detected."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": sensitive_path},
            workspace=Path("/tmp"),
        )
        
        assert allowed is False, f"Should block {sensitive_path}"
        assert audit is not None
        assert audit.reason == DenialReason.SENSITIVE_FILE

    def test_additional_sensitive_patterns(self):
        """Additional sensitive patterns should be added."""
        config = SecurityConfig(
            enabled=True,
            additional_sensitive_patterns=[r"custom_secret_\w+\.txt"],
        )
        guard = ToolSecurityGuard(config)
        
        allowed, _, _ = guard.check_tool(
            "read_file",
            {"path": "/tmp/custom_secret_api.txt"},
            workspace=Path("/tmp"),
        )
        
        assert allowed is False

    def test_additional_blocked_paths(self):
        """Additional blocked paths should be added."""
        config = SecurityConfig(
            enabled=True,
            additional_blocked_paths=["/custom/blocked/"],
        )
        guard = ToolSecurityGuard(config)
        
        allowed, _, _ = guard.check_tool(
            "read_file",
            {"path": "/custom/blocked/file.txt"},
            workspace=Path("/tmp"),
        )
        
        assert allowed is False

    def test_audit_logging(self):
        """Audit entries should be created for denials."""
        config = SecurityConfig(enabled=True, audit_enabled=True)
        guard = ToolSecurityGuard(config)
        
        guard.check_tool(
            "read_file",
            {"path": "/tmp/.env"},
            workspace=Path("/workspace"),
            session_key="test_session",
            channel="cli",
        )
        
        denials = guard.get_recent_denials()
        assert len(denials) == 1
        assert denials[0].tool_name == "read_file"
        assert denials[0].session_key == "test_session"
        assert denials[0].channel == "cli"
        assert denials[0].allowed is False

    def test_audit_callback(self):
        """Audit callback should be called."""
        callback_called = []
        
        def callback(entry):
            callback_called.append(entry)
        
        config = SecurityConfig(
            enabled=True,
            audit_enabled=True,
            audit_callback=callback,
        )
        guard = ToolSecurityGuard(config)
        
        guard.check_tool(
            "read_file",
            {"path": "/tmp/.env"},
            workspace=Path("/workspace"),
        )
        
        assert len(callback_called) == 1
        assert callback_called[0].tool_name == "read_file"

    def test_clear_audit_log(self):
        """Audit log should be clearable."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        guard.check_tool("read_file", {"path": "/tmp/.env"}, workspace=Path("/workspace"))
        assert len(guard.get_recent_denials()) == 1
        
        guard.clear_audit_log()
        assert len(guard.get_recent_denials()) == 0

    def test_sanitize_params_audit(self):
        """Sensitive parameters should be redacted in audit."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        guard.check_tool(
            "read_file",
            {"path": "/tmp/.env", "password": "secret123", "api_key": "abc123"},
            workspace=Path("/workspace"),
        )
        
        denials = guard.get_recent_denials()
        assert len(denials) == 1
        params = denials[0].parameters
        assert params.get("password") == "[REDACTED]"
        assert params.get("api_key") == "[REDACTED]"


class TestToolRegistryIntegration:
    """Tests for ToolRegistry integration with security guard."""

    def test_registry_creates_default_guard(self):
        """Registry should create a default guard if none provided."""
        registry = ToolRegistry()
        assert registry.security_guard is not None
        assert registry.security_guard.enabled is False

    def test_registry_uses_provided_guard(self):
        """Registry should use the provided guard."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        registry = ToolRegistry(security_guard=guard)
        
        assert registry.security_guard is guard

    def test_registry_passes_workspace_to_guard(self, tmp_path):
        """Registry should pass workspace to guard during checks."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        registry = ToolRegistry(security_guard=guard, workspace=workspace)
        
        from nanobot.agent.tools.base import Tool
        from typing import Any
        
        class FakeTool(Tool):
            @property
            def name(self):
                return "read_file"
            
            @property
            def description(self):
                return "Read file"
            
            @property
            def parameters(self):
                return {"type": "object", "properties": {"path": {"type": "string"}}}
            
            async def execute(self, **kwargs):
                return kwargs
        
        registry.register(FakeTool())
        
        tool, params, error = registry.prepare_call("read_file", {"path": str(tmp_path / "outside" / "file.txt")})
        
        assert tool is not None
        assert error is not None
        assert "outside" in error.lower() or "workspace" in error.lower()

    def test_registry_set_context(self):
        """Registry should set context for auditing."""
        registry = ToolRegistry()
        registry.set_context(channel="slack", session_key="test:123")
        
        assert registry._channel == "slack"
        assert registry._session_key == "test:123"


class TestDefaultGuard:
    """Tests for default guard singleton."""

    def test_get_default_guard_returns_singleton(self):
        """get_default_guard should return the same instance."""
        guard1 = get_default_guard()
        guard2 = get_default_guard()
        
        assert guard1 is guard2

    def test_configure_guard_updates_default(self):
        """configure_guard should update the default guard."""
        config = SecurityConfig(enabled=True, denied_tools=["exec"])
        configure_guard(config)
        
        guard = get_default_guard()
        assert guard.config.enabled is True


class TestSensitiveFilePatterns:
    """Tests for sensitive file pattern coverage."""

    def test_patterns_are_valid_regex(self):
        """All patterns should be valid regular expressions."""
        import re
        
        for pattern in _SENSITIVE_FILE_PATTERNS:
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(f"Invalid pattern '{pattern}': {e}")

    @pytest.mark.parametrize("test_input,expected_match", [
        (".env", True),
        (".env.local", True),
        ("config.env", True),
        ("id_rsa", True),
        ("id_rsa.pub", True),
        ("id_dsa", True),
        ("id_ecdsa", True),
        ("id_ed25519", True),
        ("server.key", True),
        ("private.pem", True),
        ("cert.pfx", True),
        ("keystore.jks", True),
        ("secrets.yml", True),
        ("credentials.json", True),
        ("api_key.txt", True),
        ("access_token", True),
        ("password.txt", True),
        ("~/.aws/credentials", True),
        ("~/.kube/config", True),
        ("~/.npmrc", True),
        ("~/.netrc", True),
        ("database.yml", True),
        ("application.properties", True),
        ("normal.txt", False),
        ("readme.md", False),
        ("src/main.py", False),
        ("public/index.html", False),
    ])
    def test_pattern_matching(self, test_input, expected_match):
        """Patterns should match/unmatch expected inputs."""
        import re
        
        matched = False
        for pattern in _SENSITIVE_FILE_PATTERNS:
            if re.search(pattern, test_input, re.IGNORECASE):
                matched = True
                break
        
        assert matched == expected_match, f"Pattern matching for '{test_input}': expected {expected_match}, got {matched}"
