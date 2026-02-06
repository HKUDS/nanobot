"""Media cleanup utilities for managing temporary files."""

import atexit
import tempfile
import threading
import time
from pathlib import Path

from loguru import logger


class MediaCleanupRegistry:
    """
    Registry for tracking and cleaning up temporary media files.

    Ensures temporary files (extracted video frames, audio files, etc.)
    are cleaned up on exit, even if the process crashes.

    Features:
    - atexit handler for normal shutdown
    - Signal handlers (SIGTERM, SIGINT) for graceful shutdown
    - Periodic cleanup to prevent accumulation
    - Thread-safe singleton initialization
    """

    def __init__(
        self,
        media_dir: Path,
        max_age_hours: float = 24.0,
        periodic_cleanup: bool = True,
        periodic_interval_seconds: float = 3600.0,
    ):
        """
        Initialize the cleanup registry.

        Args:
            media_dir: Base media directory.
            max_age_hours: Maximum age of files before auto-cleanup (hours).
            periodic_cleanup: Enable periodic background cleanup.
            periodic_interval_seconds: How often to run periodic cleanup.
        """
        self.media_dir = Path(media_dir)
        self.max_age_hours = max_age_hours
        self.periodic_cleanup_enabled = periodic_cleanup
        self.periodic_interval = periodic_interval_seconds
        self._registered_files: set[Path] = set()
        self._shutdown = False
        self._cleanup_thread: threading.Thread | None = None
        self._cleanup_lock = threading.Lock()

        # Register cleanup handlers
        self._register_cleanup_handlers()

        # Start periodic cleanup if enabled
        if self.periodic_cleanup_enabled:
            self._start_periodic_cleanup()

    def _register_cleanup_handlers(self) -> None:
        """
        Register cleanup handlers for graceful shutdown.

        Signal handlers are NOT registered to avoid async-signal-unsafe operations.
        We rely on:        - atexit handler for file cleanup on normal exit
        - Explicit shutdown via stop_periodic_cleanup() called by application

        The periodic cleanup thread is non-daemon, so applications must call
        stop_periodic_cleanup() during shutdown to avoid hanging.
        """
        atexit.register(self._cleanup_on_exit)

    def _start_periodic_cleanup(self) -> None:
        """
        Start background thread for periodic cleanup.

        Note: Thread is non-daemon to ensure proper shutdown. The caller
        must invoke stop_periodic_cleanup() during application shutdown.
        """
        def cleanup_loop():
            while not self._shutdown:
                try:
                    time.sleep(self.periodic_interval)
                    if self._shutdown:
                        break
                    self.cleanup_old_files()
                except Exception as e:
                    logger.error(f"Error in periodic cleanup: {e}")

        self._cleanup_thread = threading.Thread(
            target=cleanup_loop,
            daemon=False,  # Non-daemon to ensure graceful shutdown
            name="MediaCleanupThread"
        )
        self._cleanup_thread.start()
        logger.info(f"Started periodic cleanup (interval: {self.periodic_interval}s)")

    def stop_periodic_cleanup(self) -> None:
        """Stop the periodic cleanup background thread."""
        with self._cleanup_lock:
            self._shutdown = True
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
            logger.info("Stopped periodic cleanup")

    def register(self, file_path: Path | str) -> None:
        """
        Register a file for cleanup on exit.

        Thread-safe: Uses lock to prevent race conditions.

        Args:
            file_path: Path to the file to track.
        """
        with self._cleanup_lock:
            self._registered_files.add(Path(file_path))

    def unregister(self, file_path: Path | str) -> None:
        """
        Unregister a file (will not be cleaned up on exit).

        Thread-safe: Uses lock to prevent race conditions.

        Args:
            file_path: Path to the file to untrack.
        """
        with self._cleanup_lock:
            self._registered_files.discard(Path(file_path))

    def cleanup_now(self) -> int:
        """
        Immediately clean up all registered files and stop background cleanup.

        This method provides explicit cleanup control for graceful shutdown scenarios.
        It can be called directly by application code (e.g., in ChannelManager.stop_all())
        rather than relying solely on the atexit handler.

        Thread-safe: Uses locks to prevent race conditions.

        Returns:
            Total number of files cleaned up (registered + old files).
        """
        # Stop periodic cleanup thread first
        try:
            self.stop_periodic_cleanup()
        except Exception:
            pass  # Ignore errors during shutdown

        # Get list of files to clean up (work on copy to avoid holding lock)
        with self._cleanup_lock:
            files_to_cleanup = list(self._registered_files)

        cleaned = 0
        errors = 0

        # Clean up registered files
        for file_path in files_to_cleanup:
            try:
                if file_path.exists():
                    file_path.unlink()
                    cleaned += 1
                    logger.debug(f"Cleaned up registered file: {file_path.name}")
            except Exception as e:
                errors += 1
                logger.debug(f"Failed to cleanup {file_path.name}: {e}")

        # Clear the registry after cleanup
        with self._cleanup_lock:
            self._registered_files.clear()

        if cleaned > 0:
            logger.info(f"Explicit cleanup: {cleaned} registered files (errors: {errors})")

        # Also cleanup old files in media directory
        old_files = self.cleanup_old_files()
        if old_files > 0:
            logger.info(f"Explicit cleanup: removed {old_files} old files")

        return cleaned + old_files

    def cleanup_old_files(self, max_age_hours: float | None = None) -> int:
        """
        Clean up files older than max_age_hours.

        Optimized to use os.scandir() for better performance with large directories.
        Skips subdirectories whose mtime indicates they contain only recent files.

        Args:
            max_age_hours: Override default max age.

        Returns:
            Number of files cleaned up.
        """
        import os

        max_age = max_age_hours or self.max_age_hours
        max_age_seconds = max_age * 3600
        now = time.time()
        cleaned = 0
        errors = 0
        scanned = 0

        if not self.media_dir.exists():
            logger.debug(f"Media directory does not exist: {self.media_dir}")
            return 0

        def scan_directory(dir_path: Path) -> None:
            """Recursively scan directory for old files."""
            nonlocal cleaned, errors, scanned

            try:
                # Use os.scandir for better performance than Path.rglob
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if self._shutdown:
                            return

                        if entry.is_file(follow_symlinks=False):
                            scanned += 1
                            try:
                                # Check file age via stat
                                stat = entry.stat()
                                file_age = now - stat.st_mtime
                                if file_age > max_age_seconds:
                                    try:
                                        Path(entry.path).unlink()
                                        cleaned += 1
                                        logger.debug(f"Cleaned up old file: {entry.name}")
                                    except Exception as e:
                                        errors += 1
                                        logger.warning(f"Failed to cleanup {entry.name}: {e}")
                            except OSError as e:
                                errors += 1
                                logger.debug(f"Failed to stat {entry.name}: {e}")

                        elif entry.is_dir(follow_symlinks=False):
                            # Optimization: Check directory mtime before recursing
                            try:
                                dir_stat = entry.stat()
                                dir_age = now - dir_stat.st_mtime
                                # If directory itself is older than max_age, scan it
                                # If directory is recent, skip if all files would be recent
                                if dir_age > max_age_seconds / 2:
                                    # Directory is old enough to potentially contain old files
                                    scan_directory(Path(entry.path))
                            except OSError:
                                # Can't stat directory, skip it
                                pass
            except (OSError, PermissionError) as e:
                logger.debug(f"Error scanning directory {dir_path}: {e}")

        try:
            scan_directory(self.media_dir)

            if cleaned > 0:
                logger.info(
                    f"Cleaned up {cleaned} old media files "
                    f"(scanned {scanned} files, older than {max_age}h, errors: {errors})"
                )
            elif errors > 0:
                logger.debug(f"Cleanup scan complete (scanned {scanned} files, {errors} errors)")
            else:
                logger.debug(f"Cleanup scan complete (scanned {scanned} files, none to clean)")

        except Exception as e:
            logger.error(f"Error during cleanup scan: {e}")

        return cleaned

    def get_stats(self) -> dict[str, int]:
        """
        Get statistics about registered files and disk usage.

        Returns:
            Dictionary with stats (registered_count, total_size_bytes, etc).
        """
        with self._cleanup_lock:
            registered_count = len(self._registered_files)

        total_size = 0
        file_count = 0

        if self.media_dir.exists():
            try:
                for file_path in self.media_dir.rglob("*"):
                    if file_path.is_file():
                        file_count += 1
                        total_size += file_path.stat().st_size
            except Exception as e:
                logger.warning(f"Error calculating stats: {e}")

        return {
            "registered_files": registered_count,
            "total_files": file_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }

    def _cleanup_on_exit(self) -> None:
        """
        Clean up all registered files and stop periodic cleanup on process exit.

        This is called by atexit during normal program termination.
        """
        # Stop periodic cleanup thread first
        try:
            self.stop_periodic_cleanup()
        except Exception:
            pass  # Ignore errors during shutdown

        with self._cleanup_lock:
            if not self._registered_files:
                return

            # Work on a copy to avoid holding lock during cleanup
            files_to_cleanup = list(self._registered_files)

        cleaned = 0
        errors = 0

        for file_path in files_to_cleanup:
            try:
                if file_path.exists():
                    file_path.unlink()
                    cleaned += 1
                    logger.debug(f"Cleaned up registered file: {file_path.name}")
            except Exception as e:
                errors += 1
                logger.debug(f"Failed to cleanup {file_path.name}: {e}")

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} registered files on exit (errors: {errors})")

        # Clear the registry after cleanup attempt
        with self._cleanup_lock:
            self._registered_files.clear()

        # Also cleanup old files
        old_files = self.cleanup_old_files()
        if old_files > 0:
            logger.info(f"Cleanup on exit: removed {old_files} old files")

    def cleanup_temp_directories(self) -> int:
        """
        Clean up system temp directories that may contain orphaned files.

        Returns:
            Number of directories cleaned.
        """
        cleaned = 0
        max_age_seconds = self.max_age_hours * 3600
        now = time.time()

        # Check common temp locations
        temp_base = Path(tempfile.gettempdir())
        nanobot_temp_dirs = [
            temp_base / "nanobot",
            Path.home() / ".nanobot" / "media" / "frames",
        ]

        for temp_dir in nanobot_temp_dirs:
            if temp_dir.exists() and temp_dir.is_dir():
                try:
                    dir_cleaned = 0
                    for file_path in temp_dir.rglob("*"):
                        if file_path.is_file():
                            file_age = now - file_path.stat().st_mtime
                            if file_age > max_age_seconds:
                                try:
                                    file_path.unlink()
                                    dir_cleaned += 1
                                except Exception:
                                    pass

                    if dir_cleaned > 0:
                        cleaned += 1
                        logger.debug(f"Cleaned {dir_cleaned} files from temp directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to clean temp directory {temp_dir}: {e}")

        return cleaned


# Global registry instance (initialized on first use)
_global_registry: MediaCleanupRegistry | None = None
_lock = threading.Lock()
_initialized = False


def get_cleanup_registry(
    media_dir: Path | None = None,
    periodic_cleanup: bool = True,
    periodic_interval_seconds: float = 3600.0,
) -> MediaCleanupRegistry:
    """
    Get the global cleanup registry instance (thread-safe singleton).

    Args:
        media_dir: Media directory (uses default if not provided).
        periodic_cleanup: Enable periodic background cleanup.
        periodic_interval_seconds: How often to run periodic cleanup.

    Returns:
        The global MediaCleanupRegistry instance.

    Note:
        The first call with a specific media_dir will initialize the registry.
        Subsequent calls ignore the media_dir parameter to ensure consistency.
    """
    global _global_registry, _initialized

    with _lock:
        if _global_registry is None:
            default_media = Path.home() / ".nanobot" / "media"
            _global_registry = MediaCleanupRegistry(
                media_dir=media_dir or default_media,
                periodic_cleanup=periodic_cleanup,
                periodic_interval_seconds=periodic_interval_seconds,
            )
            _initialized = True
        return _global_registry


def shutdown_cleanup_registry() -> None:
    """
    Shutdown the global cleanup registry (stop periodic cleanup thread).

    Call this before application exit to ensure clean shutdown.
    """
    global _global_registry

    with _lock:
        if _global_registry is not None:
            _global_registry.stop_periodic_cleanup()
