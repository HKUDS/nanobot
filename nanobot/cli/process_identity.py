"""Give nanobot processes recognizable operating-system names."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

from setproctitle import setproctitle

_ROLES: Final = {"agent", "gateway", "webui"}


def set_cli_process_identity(args: list[str]) -> None:
    """Name this CLI process after the nanobot role it is running."""
    if os.name == "nt":
        # Windows process managers use the console launcher's executable name,
        # which packaging already generates as ``nanobot.exe``.
        return
    role = args[0] if args and args[0] in _ROLES else None
    setproctitle(f"nanobot-{role}" if role else "nanobot")


def named_executable(executable: str, *, name: str, directory: Path) -> str:
    """Return a stable POSIX symlink whose basename identifies a child process."""
    if os.name == "nt":
        return executable
    try:
        target = Path(executable).resolve(strict=True)
        digest = hashlib.sha256(os.fsencode(target)).hexdigest()[:12]
        link_dir = directory / digest
        link = link_dir / name
        link_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if link.is_symlink() and link.resolve(strict=False) == target:
            return str(link)
        if link.exists():
            return executable
        pending = link.with_name(f".{name}.{os.getpid()}")
        pending.unlink(missing_ok=True)
        pending.symlink_to(target)
        os.replace(pending, link)
    except OSError:
        return executable
    return str(link)
