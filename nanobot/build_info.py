"""Source revision of the running installation and built distributions."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def read_commit(root: Path) -> str | None:
    """Read this checkout's HEAD, or the revision recorded when packaging it."""
    if (root / ".git").exists():
        try:
            commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    else:
        try:
            commit = (root / "nanobot" / "_build_commit.txt").read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return commit if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) else None


COMMIT = read_commit(Path(__file__).resolve().parent.parent)
