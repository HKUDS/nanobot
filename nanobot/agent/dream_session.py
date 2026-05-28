"""Dream session key generation and rotation for WebUI visualization."""
from datetime import datetime
from pathlib import Path

from loguru import logger


def dream_session_key() -> str:
    """Return a unique session key for a Dream run, e.g. ``dream:20260528-100000``."""
    return f"dream:{datetime.now():%Y%m%d-%H%M%S}"


def prune_dream_sessions(sessions_dir: Path, *, keep: int = 10) -> None:
    """Remove the oldest Dream session files, keeping only the N most recent.

    Only files matching ``dream_*.jsonl`` are considered. Non-dream session
    files are never touched.
    """
    dream_files = sorted(sessions_dir.glob("dream_*.jsonl"))
    if len(dream_files) <= keep:
        return

    to_remove = dream_files[: len(dream_files) - keep]
    for path in to_remove:
        try:
            path.unlink()
            logger.debug("Pruned old dream session: {}", path.stem)
        except OSError:
            logger.warning("Failed to prune dream session {}", path)
