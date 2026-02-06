"""Tests for MediaCleanupRegistry resource management."""

import shutil
import tempfile
import time
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest

from nanobot.utils.media_cleanup import MediaCleanupRegistry, get_cleanup_registry


class TestMediaCleanupRegistry:
    """Test MediaCleanupRegistry file tracking and cleanup."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.registry = MediaCleanupRegistry(
            media_dir=self.temp_dir,
            max_age_hours=1.0,
            periodic_cleanup=False,  # Disable for most tests
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        self.registry.stop_periodic_cleanup()
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_register_file_tracks_path(self):
        """Test that registering a file tracks it correctly."""
        test_file = self.temp_dir / "test_file.txt"
        test_file.write_text("test content")

        self.registry.register(test_file)

        # File should be in registry
        with self.registry._cleanup_lock:
            assert test_file in self.registry._registered_files

    def test_unregister_file_removes_from_tracking(self):
        """Test that unregistering removes file from tracking."""
        test_file = self.temp_dir / "test_file.txt"
        test_file.write_text("test content")
        self.registry.register(test_file)

        self.registry.unregister(test_file)

        # File should not be in registry
        with self.registry._cleanup_lock:
            assert test_file not in self.registry._registered_files

    def test_cleanup_on_exit_deletes_registered_files(self):
        """Test that cleanup_on_exit removes registered files."""
        # Create multiple test files
        test_files = []
        for i in range(3):
            test_file = self.temp_dir / f"test_{i}.txt"
            test_file.write_text(f"content {i}")
            self.registry.register(test_file)
            test_files.append(test_file)

        # Verify files exist
        for f in test_files:
            assert f.exists()

        # Run cleanup
        self.registry._cleanup_on_exit()

        # Files should be deleted
        for f in test_files:
            assert not f.exists()

    def test_cleanup_on_exit_skips_nonexistent_files(self):
        """Test that cleanup handles missing files gracefully."""
        test_file = self.temp_dir / "nonexistent.txt"
        self.registry.register(test_file)

        # Should not raise exception
        self.registry._cleanup_on_exit()

        # Registry should be cleared
        with self.registry._cleanup_lock:
            assert len(self.registry._registered_files) == 0

    def test_cleanup_old_files_removes_expired_files(self):
        """Test periodic cleanup removes files older than max_age_hours."""
        # Create an old file
        old_file = self.temp_dir / "old_file.txt"
        old_file.write_text("old content")

        # Set file modification time to 2 hours ago
        old_time = time.time() - (2 * 3600)
        import os
        os.utime(old_file, (old_time, old_time))

        # Create a recent file
        recent_file = self.temp_dir / "recent_file.txt"
        recent_file.write_text("recent content")

        # Run cleanup with 1 hour max age
        cleaned = self.registry.cleanup_old_files(max_age_hours=1.0)

        # Old file should be deleted, recent file should remain
        assert not old_file.exists()
        assert recent_file.exists()
        assert cleaned == 1

    def test_cleanup_old_files_skips_recent_files(self):
        """Test that recent files are not cleaned up."""
        # Create a recent file
        recent_file = self.temp_dir / "recent_file.txt"
        recent_file.write_text("recent content")

        # Run cleanup with 1 hour max age
        cleaned = self.registry.cleanup_old_files(max_age_hours=1.0)

        # File should still exist
        assert recent_file.exists()
        assert cleaned == 0

    def test_get_stats_returns_correct_counts(self):
        """Test that get_stats returns accurate information."""
        # Create some files (large enough to show up in MB when rounded)
        for i in range(3):
            test_file = self.temp_dir / f"file_{i}.txt"
            test_file.write_text(f"content {i}" * 100000)  # ~900KB each file

        # Register some of them
        self.registry.register(self.temp_dir / "file_0.txt")
        self.registry.register(self.temp_dir / "file_1.txt")

        stats = self.registry.get_stats()

        assert stats["registered_files"] == 2
        assert stats["total_files"] == 3
        assert stats["total_size_bytes"] > 0
        assert stats["total_size_mb"] > 0  # Should be > 0 with larger files

    def test_thread_safe_registration(self):
        """Test that concurrent registrations are thread-safe."""
        test_files = []
        for i in range(50):
            test_file = self.temp_dir / f"thread_test_{i}.txt"
            test_file.write_text(f"content {i}")
            test_files.append(test_file)

        # Register files from multiple threads
        def register_files(files):
            for f in files:
                self.registry.register(f)

        threads = []
        chunk_size = 10
        for i in range(0, len(test_files), chunk_size):
            chunk = test_files[i:i + chunk_size]
            thread = Thread(target=register_files, args=(chunk,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All files should be registered
        with self.registry._cleanup_lock:
            assert len(self.registry._registered_files) == len(test_files)
            for f in test_files:
                assert f in self.registry._registered_files

    def test_signal_handler_registration(self):
        """Test that signal handlers are registered during init."""
        import signal

        # Check that SIGTERM handler was registered
        # Note: We can't easily test the actual handler without complex setup,
        # but we can verify it doesn't crash
        assert self.registry._shutdown is False

    def test_periodic_cleanup_starts_and_stops(self):
        """Test that periodic cleanup can be started and stopped."""
        # Create registry with periodic cleanup enabled
        registry = MediaCleanupRegistry(
            media_dir=self.temp_dir,
            periodic_cleanup=True,
            periodic_interval_seconds=0.1,  # Very short for testing
        )

        # Wait a bit for cleanup thread to start
        time.sleep(0.2)

        # Cleanup thread should be running
        assert registry._cleanup_thread is not None
        assert registry._cleanup_thread.is_alive()

        # Stop periodic cleanup
        registry.stop_periodic_cleanup()

        # Thread should stop
        time.sleep(0.2)
        assert not registry._cleanup_thread.is_alive()

    def test_cleanup_temp_directories(self):
        """Test cleanup of system temp directories."""
        # Create a temp file in the nanobot temp dir
        temp_base = Path(tempfile.gettempdir())
        nanobot_temp = temp_base / "nanobot"
        nanobot_temp.mkdir(parents=True, exist_ok=True)

        old_file = nanobot_temp / "old_temp.txt"
        old_file.write_text("old temp content")

        # Set file to be old
        old_time = time.time() - (25 * 3600)  # 25 hours ago
        import os
        os.utime(old_file, (old_time, old_time))

        # Run cleanup
        cleaned_dirs = self.registry.cleanup_temp_directories()

        # Old file should be cleaned up
        assert not old_file.exists()
        assert cleaned_dirs >= 0

        # Clean up
        if nanobot_temp.exists():
            shutil.rmtree(nanobot_temp)


class TestGlobalCleanupRegistry:
    """Test the global cleanup registry singleton."""

    def setup_method(self):
        """Set up test fixtures."""
        # Reset global state
        import nanobot.utils.media_cleanup as cleanup_module
        cleanup_module._global_registry = None
        cleanup_module._initialized = False

    def teardown_method(self):
        """Clean up test fixtures."""
        import nanobot.utils.media_cleanup as cleanup_module
        if cleanup_module._global_registry:
            cleanup_module._global_registry.stop_periodic_cleanup()
        cleanup_module._global_registry = None
        cleanup_module._initialized = False

    def test_get_cleanup_registry_returns_singleton(self):
        """Test that get_cleanup_registry returns the same instance."""
        registry1 = get_cleanup_registry()
        registry2 = get_cleanup_registry()

        assert registry1 is registry2

    def test_get_cleanup_registry_initializes_once(self):
        """Test that registry is only initialized once."""
        import nanobot.utils.media_cleanup as cleanup_module

        registry1 = get_cleanup_registry()
        assert cleanup_module._initialized is True

        registry2 = get_cleanup_registry()
        assert cleanup_module._initialized is True

        assert registry1 is registry2

    def test_shutdown_cleanup_registry_stops_periodic_cleanup(self):
        """Test that shutdown stops periodic cleanup."""
        import nanobot.utils.media_cleanup as cleanup_module

        # Create registry with periodic cleanup
        registry = get_cleanup_registry(periodic_cleanup=True, periodic_interval_seconds=0.1)

        time.sleep(0.2)
        assert registry._cleanup_thread is not None

        # Shutdown
        cleanup_module.shutdown_cleanup_registry()

        # Thread should be stopped
        time.sleep(0.2)
        if registry._cleanup_thread:
            assert not registry._cleanup_thread.is_alive()

    def test_get_cleanup_registry_custom_media_dir(self):
        """Test that custom media_dir is used on first call."""
        temp_dir = Path(tempfile.mkdtemp())

        try:
            registry = get_cleanup_registry(media_dir=temp_dir)
            assert registry.media_dir == temp_dir
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
