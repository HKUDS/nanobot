"""Backup rotation for ``USER.md`` before L3 writes."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from loguru import logger

from nanobot.utils.helpers import ensure_dir

_BACKUP_DIR = ".nanobot/persona_backups"
_USER_NAME = "USER.md"


def user_file_path(workspace: Path) -> Path:
    return workspace / _USER_NAME


def backup_user_md(workspace: Path, *, keep: int) -> Path | None:
    """Copy current ``USER.md`` into backup dir; prune to ``keep`` newest copies."""
    source = user_file_path(workspace)
    if not source.is_file():
        return None
    backup_dir = ensure_dir(workspace / _BACKUP_DIR)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    dest = backup_dir / f"USER.{stamp}.md"
    shutil.copy2(source, dest)
    logger.debug("layered_memory persona_backup path={}", dest)
    if keep > 0:
        _prune_backups(backup_dir, keep=keep)
    return dest


def list_backups(workspace: Path) -> list[Path]:
    backup_dir = workspace / _BACKUP_DIR
    if not backup_dir.is_dir():
        return []
    files = sorted(backup_dir.glob("USER.*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _prune_backups(backup_dir: Path, *, keep: int) -> None:
    files = sorted(backup_dir.glob("USER.*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[keep:]:
        path.unlink(missing_ok=True)
