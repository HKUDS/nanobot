"""Pluggable tool-guard system for pre-execution security checks.

Guards are executed **before** each tool invocation.  They can inspect the
tool name, resolved parameters, and optional execution context to decide
whether the call should proceed.

Built-in guards:
    - ``DeniedPathsGuard``  – blocks file-system tools from accessing
      protected paths (config dir, etc.).  Uses resolved-path comparison,
      so it is not bypassable via symlinks or ``..``.
    - ``PatternGuard``      – blocks shell commands matching dangerous
      regex patterns (``rm -rf``, fork bombs …).
    - ``NetworkGuard``      – blocks shell commands targeting internal
      / private URLs (SSRF protection).

Third-party or user-defined guards can be added by subclassing
``ToolGuard`` and registering instances on the ``ToolRegistry``.
"""

from __future__ import annotations

import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Outcome of a single guard check.

    *allowed* – ``True`` if the tool call may proceed.
    *reason*  – human-readable explanation when the call is blocked.
    """
    allowed: bool
    reason: str = ""

    @staticmethod
    def ok() -> "GuardResult":
        return GuardResult(allowed=True)

    @staticmethod
    def block(reason: str) -> "GuardResult":
        return GuardResult(allowed=False, reason=reason)


# ---------------------------------------------------------------------------
# Context passed to every guard
# ---------------------------------------------------------------------------

@dataclass
class GuardContext:
    """Execution context available to guards at check time."""
    tool_name: str
    params: dict[str, Any]
    working_dir: str | None = None
    # Extensible: guards may read extra fields added by the caller.
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class ToolGuard(ABC):
    """Base class for pluggable tool guards.

    Subclass and implement :meth:`check` to create a custom guard.
    Guards are evaluated in registration order; the first ``block``
    result short-circuits further checks.
    """

    @property
    def name(self) -> str:
        """Human-readable guard name (for logging / error messages)."""
        return type(self).__name__

    @abstractmethod
    def check(self, ctx: GuardContext) -> GuardResult:
        """Return ``GuardResult.ok()`` or ``GuardResult.block(reason)``."""
        ...

    # Optional: list of tool names this guard applies to.
    # ``None`` means *all* tools.
    tool_names: list[str] | None = None

    def applies_to(self, tool_name: str) -> bool:
        """Return True if this guard should run for *tool_name*."""
        if self.tool_names is None:
            return True
        return tool_name in self.tool_names


# ===================================================================
# Built-in guards
# ===================================================================

# ---------------------------------------------------------------------------
# DeniedPathsGuard  (file-system tools)
# ---------------------------------------------------------------------------

class DeniedPathsGuard(ToolGuard):
    """Block file-system tools from accessing protected paths.

    Works on *resolved* paths so symlinks/``..`` cannot bypass it.
    This guard does **not** apply to the ``exec`` tool — shell-level
    protection requires either ``BwrapGuard`` or ``PatternGuard``.
    """

    tool_names = ["read_file", "write_file", "edit_file", "list_dir"]

    def __init__(self, denied_paths: list[Path]) -> None:
        self._denied: list[Path] = [p.expanduser().resolve() for p in denied_paths]

    def check(self, ctx: GuardContext) -> GuardResult:
        raw_path = ctx.params.get("path")
        if raw_path is None:
            return GuardResult.ok()

        try:
            p = Path(raw_path).expanduser()
            if not p.is_absolute() and ctx.working_dir:
                p = Path(ctx.working_dir) / p
            resolved = p.resolve()
        except Exception:
            return GuardResult.ok()  # let the tool itself handle bad paths

        for denied in self._denied:
            if resolved == denied or self._is_under(resolved, denied):
                return GuardResult.block(
                    f"Access denied: {raw_path} is a protected path"
                )
        return GuardResult.ok()

    @staticmethod
    def _is_under(path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False


# ---------------------------------------------------------------------------
# PatternGuard  (exec tool — regex deny/allow lists)
# ---------------------------------------------------------------------------

class PatternGuard(ToolGuard):
    """Block shell commands matching dangerous regex patterns."""

    tool_names = ["exec"]

    DEFAULT_DENY = [
        r"\brm\s+-[rf]{1,2}\b",
        r"\bdel\s+/[fq]\b",
        r"\brmdir\s+/s\b",
        r"(?:^|[;&|]\s*)format\b",
        r"\b(mkfs|diskpart)\b",
        r"\bdd\s+if=",
        r">\s*/dev/sd",
        r"\b(shutdown|reboot|poweroff)\b",
        r":\(\)\s*\{.*\};\s*:",
    ]

    def __init__(
        self,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
    ) -> None:
        self._deny = deny_patterns if deny_patterns is not None else self.DEFAULT_DENY
        self._allow = allow_patterns or []

    def check(self, ctx: GuardContext) -> GuardResult:
        command = (ctx.params.get("command") or "").strip()
        if not command:
            return GuardResult.ok()

        lower = command.lower()

        for pattern in self._deny:
            if re.search(pattern, lower):
                return GuardResult.block(
                    "Command blocked by safety guard (dangerous pattern detected)"
                )

        if self._allow:
            if not any(re.search(p, lower) for p in self._allow):
                return GuardResult.block(
                    "Command blocked by safety guard (not in allowlist)"
                )

        return GuardResult.ok()


# ---------------------------------------------------------------------------
# NetworkGuard  (exec tool — SSRF protection)
# ---------------------------------------------------------------------------

class NetworkGuard(ToolGuard):
    """Block shell commands that target internal/private URLs."""

    tool_names = ["exec"]

    def check(self, ctx: GuardContext) -> GuardResult:
        command = (ctx.params.get("command") or "").strip()
        if not command:
            return GuardResult.ok()

        from nanobot.security.network import contains_internal_url

        if contains_internal_url(command):
            return GuardResult.block(
                "Command blocked by safety guard (internal/private URL detected)"
            )
        return GuardResult.ok()


# ---------------------------------------------------------------------------
# WorkspaceGuard  (exec tool — restrict to workspace)
# ---------------------------------------------------------------------------

class WorkspaceGuard(ToolGuard):
    """Block shell commands that reference paths outside the workspace."""

    tool_names = ["exec"]

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.resolve()

    def check(self, ctx: GuardContext) -> GuardResult:
        import os

        command = (ctx.params.get("command") or "").strip()
        if not command:
            return GuardResult.ok()

        if "..\\" in command or "../" in command:
            return GuardResult.block(
                "Command blocked by safety guard (path traversal detected)"
            )

        cwd = Path(ctx.working_dir or ".").resolve()

        for raw in _extract_absolute_paths(command):
            try:
                expanded = os.path.expandvars(raw.strip())
                p = Path(expanded).expanduser().resolve()
            except Exception:
                continue
            if p.is_absolute() and cwd not in p.parents and p != cwd:
                return GuardResult.block(
                    "Command blocked by safety guard (path outside working dir)"
                )

        return GuardResult.ok()


# ---------------------------------------------------------------------------
# BwrapGuard  (exec tool — Bubblewrap OS-level sandbox)
# ---------------------------------------------------------------------------

class BwrapGuard(ToolGuard):
    """Wrap shell commands in a Bubblewrap (bwrap) sandbox.

    Instead of blocking, this guard **rewrites** the command so that it
    runs inside a lightweight Linux namespace sandbox.  The sandbox:

    - Mounts the workspace read-write.
    - Mounts system paths (``/usr``, ``/bin``, ``/lib*``, ``/etc``) read-only.
    - Hides the config directory behind a tmpfs overlay.
    - Drops all capabilities except those needed for normal operation.

    If ``bwrap`` is not available on the system, the guard logs a warning
    and falls back to **allowing** the command un-sandboxed (so the agent
    doesn't break on macOS/Windows).
    """

    tool_names = ["exec"]

    def __init__(
        self,
        hidden_paths: list[Path] | None = None,
        workspace: Path | None = None,
        read_only_mounts: list[str] | None = None,
    ) -> None:
        self._hidden = [p.expanduser().resolve() for p in (hidden_paths or [])]
        self._workspace = workspace.resolve() if workspace else None
        self._ro_mounts = read_only_mounts or ["/usr", "/bin", "/lib", "/lib64", "/etc", "/sbin"]
        self._bwrap_path = shutil.which("bwrap")

    @property
    def available(self) -> bool:
        return self._bwrap_path is not None

    def check(self, ctx: GuardContext) -> GuardResult:
        # BwrapGuard does not block — it rewrites the command.
        # Rewriting happens in ``transform``.
        return GuardResult.ok()

    def transform(self, ctx: GuardContext) -> GuardContext:
        """Rewrite the command to run inside bwrap, if available."""
        if not self._bwrap_path:
            return ctx  # not available — pass through

        command = ctx.params.get("command", "")
        if not command:
            return ctx

        parts = [self._bwrap_path]

        # Read-only system mounts
        for mount in self._ro_mounts:
            parts += ["--ro-bind", mount, mount]

        # /dev, /proc, /tmp
        parts += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]

        # Hide sensitive paths behind tmpfs
        for hidden in self._hidden:
            # Overlay the *parent* directory so the entire config folder disappears
            parent = str(hidden if hidden.is_dir() else hidden.parent)
            parts += ["--tmpfs", parent]

        # Workspace: read-write
        if self._workspace:
            parts += ["--bind", str(self._workspace), str(self._workspace)]

        # Working directory
        cwd = ctx.working_dir or str(self._workspace or "/tmp")
        parts += ["--chdir", cwd]

        # Unshare namespaces
        parts += ["--unshare-all", "--share-net"]

        # The actual command
        parts += ["--", "sh", "-c", command]

        new_params = {**ctx.params, "command": " ".join(_shell_quote(p) for p in parts)}
        return GuardContext(
            tool_name=ctx.tool_name,
            params=new_params,
            working_dir=ctx.working_dir,
            extra=ctx.extra,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_absolute_paths(command: str) -> list[str]:
    """Extract absolute / home-relative paths from a shell command string."""
    win = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)
    posix = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)
    home = re.findall(r"(?:^|[\s|>'\"])(~[^\s\"'>;|<]*)", command)
    return win + posix + home


def _shell_quote(s: str) -> str:
    """Minimal POSIX shell quoting."""
    if not s:
        return "''"
    # If safe characters only, return as-is
    if re.fullmatch(r"[A-Za-z0-9_./:=@,-]+", s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"
