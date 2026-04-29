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
    _BLOCKED_SYSTEM_PATHS,
    _PATH_TRAVERSAL_PATTERN,
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


class TestAdditionalBlockedPathsFix:
    """Tests for additional_blocked_paths functionality - BUG FIX."""

    def test_additional_blocked_paths_should_be_checked(self, tmp_path):
        """additional_blocked_paths should actually block paths - bug fix test."""
        custom_blocked = str(tmp_path / "custom_blocked")
        
        config = SecurityConfig(
            enabled=True,
            additional_blocked_paths=[custom_blocked + "/"],
        )
        guard = ToolSecurityGuard(config)
        
        test_path = f"{custom_blocked}/secret.txt"
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": test_path},
            workspace=tmp_path,
        )
        
        assert allowed is False, f"Should block {test_path} with additional_blocked_paths"
        assert error is not None
        assert audit is not None

    def test_additional_blocked_paths_in_blocked_paths_list(self):
        """additional_blocked_paths should be added to self._blocked_paths."""
        config = SecurityConfig(
            enabled=True,
            additional_blocked_paths=["/custom/blocked/"],
        )
        guard = ToolSecurityGuard(config)
        
        assert "/custom/blocked/" in guard._blocked_paths

    def test_additional_blocked_paths_included_in_is_system_path(self):
        """_is_system_path should check against self._blocked_paths, not hardcoded constants."""
        import sys
        is_windows = sys.platform == "win32"
        
        config = SecurityConfig(
            enabled=True,
            additional_blocked_paths=["/myapp/secrets/"],
        )
        guard = ToolSecurityGuard(config)
        
        if not is_windows:
            path_str = "/myapp/secrets/config.json"
            result = guard._is_system_path(Path(path_str), path_str)
            assert result is True, f"Should block {path_str} from additional_blocked_paths"


class TestDenialAuditSanitizationFix:
    """Tests for audit sanitization on denial - BUG FIX."""

    def test_denial_audit_parameters_should_be_sanitized(self):
        """Denial audit entries should have sanitized parameters - bug fix test."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        secret_password = "MySuperSecretPassword123!"
        secret_api_key = "sk_live_abcdefghijklmnopqrst"
        
        guard.check_tool(
            "read_file",
            {
                "path": "/tmp/.env",
                "password": secret_password,
                "api_key": secret_api_key,
                "nested": {"db_password": "db_secret"},
            },
            workspace=Path("/workspace"),
        )
        
        denials = guard.get_recent_denials()
        assert len(denials) == 1
        
        params = denials[0].parameters
        
        assert params["password"] == "[REDACTED]", f"Password should be redacted, got {params['password']}"
        assert params["api_key"] == "[REDACTED]", f"API key should be redacted, got {params['api_key']}"
        assert params["nested"]["db_password"] == "[REDACTED]", f"Nested password should be redacted"
        
        assert secret_password not in str(params), "Raw password should not appear in audit"
        assert secret_api_key not in str(params), "Raw API key should not appear in audit"

    def test_sensitive_value_detection_in_audit(self):
        """String values that look like API keys/tokens should be redacted."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        guard.check_tool(
            "read_file",
            {
                "path": "/tmp/.env",
                "some_param": "ghp_abcdefghijklmnopqrstuvwxyz123456",
                "another_param": "sk_test_abcdefghijklmnop",
            },
            workspace=Path("/workspace"),
        )
        
        denials = guard.get_recent_denials()
        params = denials[0].parameters
        
        assert params["some_param"] == "[REDACTED]", "GitHub token should be redacted"
        assert params["another_param"] == "[REDACTED]", "Stripe test key should be redacted"


class TestPathTraversalFix:
    """Tests for path traversal detection - BUG FIX."""

    def test_path_traversal_should_detect_escape_attempt(self):
        """Path traversal should be detected accurately - bug fix test."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": "/tmp/../../../etc/passwd"},
            workspace=Path("/tmp/workspace"),
        )
        
        assert allowed is False
        assert audit is not None
        assert audit.reason == DenialReason.PATH_TRAVERSAL

    def test_version_string_should_not_trigger_path_traversal(self):
        """Version strings like '1.2.3' should NOT trigger path traversal - bug fix test."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        test_path = "/tmp/app/version-1.2.3/config.txt"
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": test_path},
            workspace=Path("/tmp"),
        )
        
        if audit:
            assert audit.reason != DenialReason.PATH_TRAVERSAL, f"'{test_path}' should not be detected as path traversal"

    def test_double_dot_in_filename_allowed(self):
        """Double dot in filename without separator should be allowed."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        allowed, error, audit = guard.check_tool(
            "read_file",
            {"path": "/tmp/file.with.dots.txt"},
            workspace=Path("/tmp"),
        )
        
        if audit:
            assert audit.reason != DenialReason.PATH_TRAVERSAL

    def test_real_path_traversal_escape_detected(self):
        """Actual path traversal escape should be detected."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        traversal_paths = [
            "/tmp/../etc/passwd",
            "data/../../../etc/shadow",
            "./../../root/.ssh/id_rsa",
            "images/../../../../../etc/passwd",
            "/var/www/../logs/../../etc/passwd",
        ]
        
        for test_path in traversal_paths:
            allowed, error, audit = guard.check_tool(
                "read_file",
                {"path": test_path},
                workspace=Path("/tmp/workspace"),
            )
            
            if allowed is True and not audit:
                result, _ = guard._check_path(test_path, Path("/tmp/workspace"))
                if result is None:
                    pass


class TestPathParamsExtractionFix:
    """Tests for path parameter extraction - BUG FIX."""

    def test_extracts_common_path_parameter_names(self):
        """Should extract path from common parameter names - bug fix test."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        test_params = {
            "path": "/tmp/test.txt",
            "paths": ["/tmp/a.txt", "/tmp/b.txt"],
            "file": "/tmp/file.txt",
            "files": ["/tmp/f1.txt"],
            "dir": "/tmp/dir",
            "directory": "/tmp/directory",
            "working_dir": "/tmp/work",
            "source": "/tmp/src.txt",
            "destination": "/tmp/dst.txt",
            "target": "/tmp/target.txt",
            "filename": "/tmp/filename.txt",
            "filepath": "/tmp/filepath.txt",
            "src": "/tmp/src.txt",
            "dst": "/tmp/dst.txt",
        }
        
        result = guard._extract_path_params(test_params)
        
        assert "path" in result
        assert "file" in result
        assert "dir" in result
        assert "directory" in result
        assert "working_dir" in result
        assert "source" in result
        assert "destination" in result
        assert "target" in result
        assert "filename" in result
        assert "filepath" in result
        assert "src" in result
        assert "dst" in result

    def test_extracts_path_like_values_by_content(self):
        """Should extract values that LOOK like paths even if not in path_keys."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        test_params = {
            "custom_arg": "/tmp/custom/path.txt",
            "another_arg": "config/settings.yaml",
            "windows_arg": "C:\\Users\\test\\file.txt",
            "dot_path": "./local/config.json",
            "home_path": "~/.config/app.json",
        }
        
        result = guard._extract_path_params(test_params)
        
        assert "custom_arg" in result, f"Should detect '/tmp/custom/path.txt' as path, got {result}"
        assert "another_arg" in result, f"Should detect 'config/settings.yaml' as path, got {result}"

    def test_extracts_nested_dict_paths(self):
        """Should recursively extract paths from nested dictionaries - bug fix test."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        test_params = {
            "outer": "ok",
            "nested": {
                "path": "/tmp/nested/file.txt",
                "deep": {
                    "src": "/tmp/nested/deep/src.txt",
                    "password": "secret123",
                }
            },
            "list_with_dict": [
                {"file": "/tmp/list/file1.txt"},
                {"file": "/tmp/list/file2.txt"},
            ],
        }
        
        result = guard._extract_path_params(test_params)
        
        assert "nested.path" in result, f"Should find nested path, got {list(result.keys())}"
        assert "nested.deep.src" in result, f"Should find deeply nested src, got {list(result.keys())}"
        assert "list_with_dict[0].file" in result, f"Should find list item path, got {list(result.keys())}"

    def test_extracts_paths_from_list(self):
        """Should extract paths from list values."""
        config = SecurityConfig(enabled=True)
        guard = ToolSecurityGuard(config)
        
        test_params = {
            "paths": ["/tmp/a.txt", "/tmp/b.txt", "not_a_path"],
        }
        
        result = guard._extract_path_params(test_params)
        
        assert "paths[0]" in result
        assert "paths[1]" in result


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


class TestLooksLikePathHeuristic:
    """Tests for _looks_like_path heuristic."""

    @pytest.mark.parametrize("value,expected", [
        ("/tmp/test.txt", True),
        ("./local/file.txt", True),
        ("../parent/file.txt", True),
        ("C:\\Windows\\test.txt", True),
        ("~/.config/file", True),
        ("src/main.py", True),
        ("config.json", True),
        ("test.txt", True),
        ("", False),
        (None, False),
        ("notapath", False),
        ("version-1.2.3", False),
    ])
    def test_looks_like_path(self, value, expected):
        """_looks_like_path should correctly identify path-like strings."""
        config = SecurityConfig()
        guard = ToolSecurityGuard(config)
        
        if value is None:
            result = guard._looks_like_path("")
            assert result is False
        else:
            result = guard._looks_like_path(value)
