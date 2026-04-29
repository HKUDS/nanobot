"""Tool security guard - lightweight permission checking and workspace protection.

This module provides:
1. Path protection - prevents access to sensitive system directories
2. Sensitive file detection - blocks access to .env, private keys, tokens, etc.
3. Tool permission control - allowlist/denylist for tools
4. Audit logging - records denied tool calls with context
"""

from __future__ import annotations

import dataclasses
import enum
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from loguru import logger


_IS_WINDOWS = sys.platform == "win32"


@dataclasses.dataclass
class SecurityConfig:
    """Configuration for tool security guard."""

    enabled: bool = False
    block_sensitive_files: bool = True
    block_system_dirs: bool = True
    block_path_traversal: bool = True
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    additional_sensitive_patterns: list[str] | None = None
    additional_blocked_paths: list[str] | None = None
    audit_enabled: bool = True
    audit_callback: Callable[[AuditEntry], None] | None = None


class DenialReason(enum.Enum):
    """Reason why a tool call was denied."""

    SENSITIVE_FILE = "sensitive_file"
    SYSTEM_DIRECTORY = "system_directory"
    PATH_TRAVERSAL = "path_traversal"
    TOOL_DENIED = "tool_denied"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    OUTSIDE_WORKSPACE = "outside_workspace"


@dataclasses.dataclass
class AuditEntry:
    """Audit entry for a security decision."""

    timestamp: datetime
    tool_name: str
    parameters: dict[str, Any]
    reason: DenialReason
    detail: str
    session_key: str | None = None
    channel: str | None = None
    allowed: bool = False


_SENSITIVE_FILE_PATTERNS: list[str] = [
    r"\.env$",
    r"\.env\.",
    r"^\.env\.",
    r"id_rsa",
    r"id_dsa",
    r"id_ecdsa",
    r"id_ed25519",
    r"\.pem$",
    r"\.key$",
    r"\.pkcs12$",
    r"\.pfx$",
    r"\.p12$",
    r"credentials",
    r"secrets",
    r"token",
    r"access_token",
    r"api_key",
    r"apikey",
    r"private_key",
    r"secret",
    r"password",
    r"passwd",
    r"\.gitcredentials",
    r"\.netrc",
    r"\.pgpass",
    r"\.my.cnf",
    r"\.my.ini",
    r"config\.json",
    r"settings\.json",
    r"auth\.json",
    r"oauth",
    r"\.aws/credentials",
    r"\.azure/credentials",
    r"\.kube/config",
    r"\.ssh/config",
    r"\.ssh/known_hosts",
    r"htpasswd",
    r"\.htpasswd",
    r"shadow",
    r"\.shadow",
    r"master\.key",
    r"deploy_key",
    r"deployment_key",
    r"session_key",
    r"cookie",
    r"session",
    r"jwt",
    r"bearer",
    r"\.npmrc",
    r"\.yarnrc",
    r"\.pypirc",
    r"pip\.conf",
    r"gemrc",
    r"bundle/config",
    r"docker/config\.json",
    r"config\.ini",
    r"settings\.ini",
    r"database\.yml",
    r"database\.yaml",
    r"database\.json",
    r"database\.properties",
    r"application\.properties",
    r"application\.yml",
    r"application\.yaml",
    r"secrets\.yml",
    r"secrets\.yaml",
    r"secrets\.json",
    r"secrets\.properties",
    r"local\.env",
    r"\.env\.local",
    r"\.env\.development",
    r"\.env\.production",
    r"\.env\.test",
    r"\.env\.staging",
    r"dev\.env",
    r"prod\.env",
    r"test\.env",
    r"staging\.env",
    r"key\.pem",
    r"cert\.pem",
    r"ssl\.key",
    r"tls\.key",
    r"private\.key",
    r"server\.key",
    r"client\.key",
    r"root\.key",
    r"ca\.key",
    r"keystore",
    r"truststore",
    r"\.jks$",
    r"\.keystore$",
    r"\.truststore$",
    r"\.p12$",
    r"\.pfx$",
    r"wallet\.dat",
    r"wallet\.json",
    r"\.ethereum/keystore",
    r"\.bitcoin/wallet",
    r"\.electrum/wallets",
    r"wallet\.dat",
    r"mnemonic",
    r"seed_phrase",
    r"recovery_phrase",
    r"backup phrase",
]


_BLOCKED_SYSTEM_PATHS: list[str] = [
    "/etc/",
    "/etc",
    "/var/",
    "/var",
    "/usr/",
    "/usr",
    "/bin/",
    "/bin",
    "/sbin/",
    "/sbin",
    "/lib/",
    "/lib",
    "/lib64/",
    "/lib64",
    "/opt/",
    "/opt",
    "/boot/",
    "/boot",
    "/dev/",
    "/dev",
    "/proc/",
    "/proc",
    "/sys/",
    "/sys",
    "/root/",
    "/root",
    "/tmp/",
    "/tmp",
    "/var/tmp/",
    "/var/tmp",
    "/run/",
    "/run",
    "/var/run/",
    "/var/run",
    "/lost+found/",
    "/lost+found",
]


_WINDOWS_BLOCKED_PATHS: list[str] = [
    "C:\\Windows\\",
    "C:\\Windows",
    "C:\\Program Files\\",
    "C:\\Program Files",
    "C:\\Program Files (x86)\\",
    "C:\\Program Files (x86)",
    "C:\\ProgramData\\",
    "C:\\ProgramData",
    "C:\\Users\\Administrator\\",
    "C:\\Users\\Administrator",
    "C:\\Users\\Public\\",
    "C:\\Users\\Public",
    "C:\\boot.ini",
    "C:\\ntldr",
    "C:\\NTDETECT.COM",
    "C:\\pagefile.sys",
    "C:\\hiberfil.sys",
    "C:\\swapfile.sys",
    "C:\\System Volume Information\\",
    "C:\\System Volume Information",
    "C:\\$Recycle.Bin\\",
    "C:\\$Recycle.Bin",
    "C:\\RECYCLER\\",
    "C:\\RECYCLER",
    "C:\\Documents and Settings\\",
    "C:\\Documents and Settings",
]


class ToolSecurityGuard:
    """Lightweight security guard for tool calls.

    This guard sits between the ToolRegistry and tool execution, providing:
    - Sensitive file access blocking
    - System directory access blocking
    - Path traversal detection
    - Tool allowlist/denylist
    - Audit logging

    All features are configurable and can be enabled/disabled individually.
    """

    def __init__(self, config: SecurityConfig | None = None):
        self._config = config or SecurityConfig()
        self._audit_log: list[AuditEntry] = []
        self._sensitive_patterns: list[re.Pattern] = []
        self._blocked_paths: list[str] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for sensitive file detection."""
        patterns = list(_SENSITIVE_FILE_PATTERNS)
        if self._config.additional_sensitive_patterns:
            patterns.extend(self._config.additional_sensitive_patterns)
        
        self._sensitive_patterns = []
        for pattern in patterns:
            try:
                self._sensitive_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                logger.warning(f"Invalid sensitive pattern: {pattern}")

        self._blocked_paths = list(_BLOCKED_SYSTEM_PATHS)
        if _IS_WINDOWS:
            self._blocked_paths.extend(_WINDOWS_BLOCKED_PATHS)
        if self._config.additional_blocked_paths:
            self._blocked_paths.extend(self._config.additional_blocked_paths)

    @property
    def enabled(self) -> bool:
        """Check if security guard is enabled."""
        return self._config.enabled

    @property
    def config(self) -> SecurityConfig:
        """Get the current configuration."""
        return self._config

    def update_config(self, config: SecurityConfig) -> None:
        """Update the configuration."""
        self._config = config
        self._compile_patterns()

    def check_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        workspace: Path | None = None,
        session_key: str | None = None,
        channel: str | None = None,
    ) -> tuple[bool, str | None, AuditEntry | None]:
        """Check if a tool call is allowed.

        Returns:
            (allowed, error_message, audit_entry)
            - allowed: True if the tool call is allowed
            - error_message: Human-readable error if denied
            - audit_entry: Audit entry for logging (always created for denials, optional for allows)
        """
        if not self._config.enabled:
            return True, None, None

        reason: DenialReason | None = None
        detail: str = ""

        if not self._is_tool_allowed(tool_name):
            if self._config.denied_tools and tool_name in self._config.denied_tools:
                reason = DenialReason.TOOL_DENIED
                detail = f"Tool '{tool_name}' is in the denylist"
            else:
                reason = DenialReason.TOOL_NOT_ALLOWED
                detail = f"Tool '{tool_name}' is not in the allowlist"

        if reason is None:
            path_params = self._extract_path_params(params)
            for path_param, path_value in path_params.items():
                check_result = self._check_path(path_value, workspace)
                if check_result is not None:
                    reason, detail = check_result
                    detail = f"Parameter '{path_param}': {detail}"
                    break

        if reason is not None:
            entry = AuditEntry(
                timestamp=datetime.now(),
                tool_name=tool_name,
                parameters=params,
                reason=reason,
                detail=detail,
                session_key=session_key,
                channel=channel,
                allowed=False,
            )
            self._record_audit(entry)
            return False, self._format_error(reason, detail), entry

        if self._config.audit_enabled:
            entry = AuditEntry(
                timestamp=datetime.now(),
                tool_name=tool_name,
                parameters=self._sanitize_params(params),
                reason=DenialReason.SENSITIVE_FILE,
                detail="allowed",
                session_key=session_key,
                channel=channel,
                allowed=True,
            )
            self._record_audit(entry)

        return True, None, None

    def _is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed based on allowlist/denylist."""
        if self._config.denied_tools and tool_name in self._config.denied_tools:
            return False
        
        if self._config.allowed_tools is not None:
            return tool_name in self._config.allowed_tools
        
        return True

    def _extract_path_params(self, params: dict[str, Any]) -> dict[str, str]:
        """Extract parameters that likely contain paths."""
        path_keys = {"path", "paths", "file", "files", "dir", "directory", "working_dir", "source", "destination", "target"}
        result: dict[str, str] = {}
        
        for key, value in params.items():
            if isinstance(value, str) and key in path_keys:
                result[key] = value
            elif isinstance(value, list) and key in path_keys:
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        result[f"{key}[{i}]"] = item
        
        return result

    def _check_path(self, path_str: str, workspace: Path | None) -> tuple[DenialReason, str] | None:
        """Check a single path for security violations.

        Returns:
            (reason, detail) if violated, None otherwise.
        """
        try:
            path = Path(path_str).expanduser()
            
            if self._config.block_path_traversal:
                if ".." in path_str or path_str.startswith("~"):
                    try:
                        resolved = path.resolve()
                    except Exception:
                        return DenialReason.PATH_TRAVERSAL, f"Path '{path_str}' contains suspicious elements"

            try:
                resolved = path.resolve()
            except Exception:
                resolved = path

            if self._config.block_sensitive_files:
                if self._is_sensitive_file(resolved):
                    return DenialReason.SENSITIVE_FILE, f"Path '{path_str}' matches a sensitive file pattern"

            if self._config.block_system_dirs:
                if self._is_system_path(resolved):
                    return DenialReason.SYSTEM_DIRECTORY, f"Path '{path_str}' is in a blocked system directory"

            if workspace is not None:
                try:
                    workspace_resolved = workspace.resolve()
                    if resolved != workspace_resolved and workspace_resolved not in resolved.parents:
                        return DenialReason.OUTSIDE_WORKSPACE, f"Path '{path_str}' is outside the workspace"
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Error checking path '{path_str}': {e}")

        return None

    def _is_sensitive_file(self, path: Path) -> bool:
        """Check if a path matches any sensitive file patterns."""
        path_str = str(path)
        path_lower = path_str.lower()
        name_lower = path.name.lower()

        for pattern in self._sensitive_patterns:
            if pattern.search(path_lower) or pattern.search(name_lower):
                return True

        return False

    def _is_system_path(self, path: Path) -> bool:
        """Check if a path is in a blocked system directory."""
        try:
            resolved = path.resolve()
            path_str = str(resolved)
            
            if _IS_WINDOWS:
                path_lower = path_str.lower()
                for blocked in _WINDOWS_BLOCKED_PATHS:
                    blocked_lower = blocked.lower()
                    if path_lower == blocked_lower or path_lower.startswith(blocked_lower + "\\"):
                        return True
            else:
                for blocked in _BLOCKED_SYSTEM_PATHS:
                    if path_str == blocked or path_str.startswith(blocked + "/"):
                        return True
        except Exception:
            pass

        return False

    def _sanitize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Sanitize parameters for audit logging (hide potential secrets)."""
        result: dict[str, Any] = {}
        sensitive_keys = {"password", "passwd", "secret", "token", "api_key", "apikey", "private_key", "credential"}
        
        for key, value in params.items():
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_keys):
                result[key] = "[REDACTED]"
            elif isinstance(value, dict):
                result[key] = self._sanitize_params(value)
            elif isinstance(value, list):
                result[key] = [self._sanitize_params(v) if isinstance(v, dict) else v for v in value]
            else:
                result[key] = value
        
        return result

    def _format_error(self, reason: DenialReason, detail: str) -> str:
        """Format an error message for the user."""
        prefix = "Error: Tool call blocked by security guard - "
        
        reason_messages = {
            DenialReason.SENSITIVE_FILE: "Sensitive file access denied",
            DenialReason.SYSTEM_DIRECTORY: "System directory access denied",
            DenialReason.PATH_TRAVERSAL: "Path traversal attempt detected",
            DenialReason.TOOL_DENIED: "Tool is denied",
            DenialReason.TOOL_NOT_ALLOWED: "Tool is not allowed",
            DenialReason.OUTSIDE_WORKSPACE: "Path outside workspace",
        }
        
        return f"{prefix}{reason_messages.get(reason, 'Access denied')}: {detail}"

    def _record_audit(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        if not self._config.audit_enabled:
            return

        self._audit_log.append(entry)

        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]

        if entry.allowed:
            logger.debug(f"Audit: Allowed tool '{entry.tool_name}' - {entry.detail}")
        else:
            logger.warning(f"Audit: Denied tool '{entry.tool_name}' ({entry.reason.value}): {entry.detail}")

        if self._config.audit_callback:
            try:
                self._config.audit_callback(entry)
            except Exception as e:
                logger.warning(f"Audit callback failed: {e}")

    def get_recent_denials(self, limit: int = 100) -> list[AuditEntry]:
        """Get recent denied tool calls."""
        denials = [e for e in self._audit_log if not e.allowed]
        return denials[-limit:]

    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()


_default_guard: ToolSecurityGuard | None = None


def get_default_guard() -> ToolSecurityGuard:
    """Get the default security guard instance."""
    global _default_guard
    if _default_guard is None:
        _default_guard = ToolSecurityGuard()
    return _default_guard


def configure_guard(config: SecurityConfig) -> None:
    """Configure the default security guard."""
    global _default_guard
    if _default_guard is None:
        _default_guard = ToolSecurityGuard(config)
    else:
        _default_guard.update_config(config)
