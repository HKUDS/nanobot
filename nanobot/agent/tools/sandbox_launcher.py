"""Resolve sandbox launchers without trusting the agent's command search path."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Literal


class SandboxLauncherError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def sandbox_platform(backend: str) -> Literal["supported", "unsupported"]:
    import sys

    return "supported" if (backend == "bwrap" and sys.platform.startswith("linux")) or (
        backend == "seatbelt" and sys.platform == "darwin"
    ) else "unsupported"


def resolve_sandbox_launcher(
    backend: str, custom_path: str = "", *, writable_roots: tuple[Path, ...] = (),
) -> str:
    """Keep default lookup unchanged; explicit overrides require a protected install.

    A configured filename is not proof of provenance. The administrator must
    trust its publisher. Root ownership and non-writable ancestors prevent
    ordinary agent processes from replacing an override before confinement.
    """
    name = "bwrap" if backend == "bwrap" else "/usr/bin/sandbox-exec"
    if not custom_path:
        launcher = shutil.which(name, path=os.defpath)
        if launcher is None:
            raise SandboxLauncherError("launcher_missing")
        return str(Path(launcher).absolute())
    if os.name != "posix":
        raise SandboxLauncherError("platform_unsupported")
    candidate = Path(custom_path)
    if not candidate.is_absolute():
        raise SandboxLauncherError("path_not_absolute")
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
            raise SandboxLauncherError("not_executable")
        for root in writable_roots:
            root = Path(os.path.expandvars(str(root))).expanduser()
            if root.is_absolute() and resolved.is_relative_to(root.resolve()):
                raise SandboxLauncherError("agent_writable")
        for item in (resolved, *resolved.parents):
            info = item.stat()
            if (info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                    or (os.geteuid() != 0 and os.access(item, os.W_OK))):
                raise SandboxLauncherError("unprotected_installation")
    except (OSError, RuntimeError):
        raise SandboxLauncherError("path_unavailable") from None
    return str(resolved)
