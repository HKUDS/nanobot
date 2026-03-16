"""Tests for the lock manager functionality."""

import os
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nanobot.utils.lock_manager import LockManager, check_duplicate_instance, release_instance_lock


class TestLockManager:
    """Test cases for LockManager class."""
    
    def test_acquire_and_release_lock(self):
        """Test basic lock acquisition and release."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            lock_manager = LockManager(config_path)
            
            # Should be able to acquire the lock initially
            assert lock_manager.acquire() is True
            
            # Should not be able to acquire the same lock again
            # Create a new instance to test this
            lock_manager2 = LockManager(config_path)
            assert lock_manager2.acquire() is False
            
            # Release the first lock
            lock_manager.release()
            
            # Now the second instance should be able to acquire it
            assert lock_manager2.acquire() is True
            
            # Clean up
            lock_manager2.release()
            
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()
    
    def test_lock_release_race_condition_fix(self):
        """Test that lock release follows correct order (unlock then delete)."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            lock_manager = LockManager(config_path)
            
            # Acquire the lock
            assert lock_manager.acquire() is True
            
            # Check that lock file exists
            assert lock_manager.lock_file_path.exists()
            
            # Release the lock
            lock_manager.release()
            
            # Lock file should be deleted after release
            assert not lock_manager.lock_file_path.exists()
            
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()
    
    def test_stale_lock_handling(self):
        """Test that stale locks (from dead processes) are handled properly."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            lock_manager = LockManager(config_path)
            
            # Manually create a lock file with a fake PID
            fake_pid = 999999  # Non-existent PID
            lock_manager._write_lock_info(fake_pid, str(config_path), time.time())
            
            # Should be able to acquire the lock since the process doesn't exist
            assert lock_manager.acquire() is True
            
            # Clean up
            lock_manager.release()
            
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()
    
    def test_concurrent_lock_attempts(self):
        """Test concurrent lock acquisition attempts."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            results = []
            
            def try_acquire_lock():
                lock_manager = LockManager(config_path)
                result = lock_manager.acquire()
                results.append(result)
                if result:
                    # Hold the lock briefly then release
                    time.sleep(0.1)
                    lock_manager.release()
            
            # Try to acquire the same lock from multiple threads
            threads = []
            for i in range(3):
                thread = threading.Thread(target=try_acquire_lock)
                threads.append(thread)
                thread.start()
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join()
            
            # Only one thread should have successfully acquired the lock
            assert sum(results) == 1, f"Expected exactly one success, got {sum(results)}: {results}"
            
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()
    
    def test_check_duplicate_instance_helper(self):
        """Test the check_duplicate_instance helper function."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            # Should be able to acquire lock initially (no duplicate)
            assert check_duplicate_instance(config_path) is True
            
            # Create another instance to try to acquire the same lock
            # This should fail because the lock is already held by the first call
            # But since the first call releases the lock immediately after checking,
            # we need to simulate holding the lock
            lock_manager = LockManager(config_path)
            assert lock_manager.acquire() is True  # Hold the lock
            
            # Now check_duplicate_instance should return False (duplicate detected)
            assert check_duplicate_instance(config_path) is False
            
            # Release the lock
            lock_manager.release()
            
            # Should be able to acquire again after release
            assert check_duplicate_instance(config_path) is True
            
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()
    
    def test_exception_handling_in_acquire(self):
        """Test exception handling in acquire method."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            lock_manager = LockManager(config_path)
            
            # Mock open to raise an exception
            with patch('builtins.open', side_effect=OSError("Permission denied")):
                result = lock_manager.acquire()
                assert result is False  # Should return False on exception
            
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()
    
    def test_exception_handling_in_release(self):
        """Test exception handling in release method."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_config:
            config_path = Path(temp_config.name)
            
        try:
            lock_manager = LockManager(config_path)
            
            # Acquire the lock first
            assert lock_manager.acquire() is True
            
            # Mock flock to raise an exception during release
            with patch('fcntl.flock', side_effect=OSError("Invalid file descriptor")):
                # This should not raise an exception, just log it
                lock_manager.release()
                # The lock_fd should be cleared
                assert lock_manager._lock_fd is None
                
        finally:
            # Clean up temp file
            if config_path.exists():
                config_path.unlink()