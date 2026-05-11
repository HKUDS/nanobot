"""One-shot legacy → multi-tenant migration for ``~/.nanobot``.

When an operator upgrades to a multi-tenant build on a host that ran the
pre-Slice-A single-user nanobot, the old layout (``sessions/``,
``workspace/``, ``memory/`` directly under ``~/.nanobot``) is incompatible
with the new per-user tree (``users/<uid>/…``). On gateway startup we
detect the legacy shape and rename the whole tree out of the way:

    ~/.nanobot                  ->  ~/.nanobot.legacy.<ISO-date>
    ~/.nanobot/config.json      (copied back into the new ~/.nanobot)

This is loud and reversible (mv it back). Pass ``NANOBOT_SKIP_LEGACY_MIGRATION=1``
to skip — useful when running tests against ``~/.nanobot`` directly.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from loguru import logger

# Legacy single-tenant subdirs whose presence (without ``users/``) indicates
# the host is running an upgrade-from-single-tenant migration scenario.
_LEGACY_SUBDIRS = ("sessions", "workspace", "memory")
_MIGRATION_LOCK_FILENAME = ".migration.lock"
_SKIP_ENV_VAR = "NANOBOT_SKIP_LEGACY_MIGRATION"


def _now_iso() -> str:
    """Return a filesystem-safe ISO-ish timestamp suffix."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _needs_migration(data_dir: Path) -> bool:
    if not data_dir.exists():
        return False
    if (data_dir / "users").exists():
        return False
    return any((data_dir / sub).is_dir() for sub in _LEGACY_SUBDIRS)


def _archive_target(parent: Path, base_name: str) -> Path:
    """Pick a unique archive name; append a counter if the bare ISO suffix collides."""
    base = parent / f"{base_name}.legacy.{_now_iso()}"
    candidate = base
    counter = 1
    while candidate.exists():
        candidate = Path(f"{base}.{counter}")
        counter += 1
    return candidate


def migrate_legacy_layout_if_needed(data_dir: Path | None = None) -> Path | None:
    """Detect legacy single-tenant state and move it aside.

    Returns the archive path if a migration ran, else ``None``.

    Idempotent: a second call after the rename observes ``users/`` (created
    by ``ensure_dir`` elsewhere) and does nothing.

    Honors ``NANOBOT_SKIP_LEGACY_MIGRATION=1`` for tests and rescue runs.
    """
    if os.environ.get(_SKIP_ENV_VAR) == "1":
        return None
    base_dir = data_dir if data_dir is not None else Path.home() / ".nanobot"
    if not _needs_migration(base_dir):
        return None

    # Lock OUTSIDE the directory we're about to rename — keeping the lockfile
    # inside base_dir would leave its descriptor pointing at the archived path
    # on POSIX and crash the cleanup on Windows.
    lock_path = base_dir.parent / f"{base_dir.name}{_MIGRATION_LOCK_FILENAME}"
    lock = FileLock(str(lock_path))
    with lock:
        if not _needs_migration(base_dir):
            return None  # Another process raced and migrated first.
        archive = _archive_target(base_dir.parent, base_dir.name)
        config_src = base_dir / "config.json"
        config_bytes: bytes | None = None
        if config_src.is_file():
            config_bytes = config_src.read_bytes()
        # Print the rollback hint BEFORE the destructive move so a partial
        # failure between move() and the recreate steps below doesn't leave
        # the operator without the archive path.
        logger.warning(
            "Legacy single-tenant state detected at {} — archiving to {}. "
            "Rollback: `mv {} {}` (or set {}=1 to skip on next start).",
            base_dir, archive, archive, base_dir, _SKIP_ENV_VAR,
        )
        shutil.move(str(base_dir), str(archive))
        # Lock down the archive — it carries the old auth.db hashes and any
        # session JSONLs that were sitting in the legacy layout.
        if sys.platform != "win32":
            try:
                os.chmod(archive, stat.S_IRWXU)  # 0o700
            except OSError as exc:
                logger.warning("could not chmod archive {}: {}", archive, exc)
        base_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(base_dir, stat.S_IRWXU)  # 0o700
            except OSError as exc:
                logger.warning("could not chmod fresh base {}: {}", base_dir, exc)
        (base_dir / "users").mkdir(exist_ok=True)
        if config_bytes is not None:
            (base_dir / "config.json").write_bytes(config_bytes)
        return archive
