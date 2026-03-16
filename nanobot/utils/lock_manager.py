"""Lock manager to prevent multiple instances with same config."""

import os
import fcntl
import json
import logging
from pathlib import Path
from typing import Optional
import psutil
import time


logger = logging.getLogger(__name__)


class LockManager:
    """Manages instance locks to prevent duplicate nanobot instances."""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.lock_file_path = self._get_lock_file_path()
        self._lock_fd = None
    
    def _get_lock_file_path(self) -> Path:
        """Get the path for the lock file based on config path."""
        # Use the config file name to create a unique lock file
        config_name = self.config_path.name
        config_hash = abs(hash(str(self.config_path.resolve()))) % 10000
        lock_filename = f"nanobot_{config_name}_{config_hash}.lock"
        
        # Use the runtime directory for lock files
        from nanobot.config.paths import get_runtime_subdir
        return get_runtime_subdir("locks") / lock_filename
    
    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is still running."""
        try:
            # Check if process exists
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def _read_lock_info(self) -> Optional[dict]:
        """Read existing lock file info."""
        if not self.lock_file_path.exists():
            return None
        
        try:
            with open(self.lock_file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def _write_lock_info(self, pid: int, config_path: str, timestamp: float):
        """Write lock info to file."""
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        lock_info = {
            "pid": pid,
            "config_path": config_path,
            "timestamp": timestamp,
            "hostname": os.uname().nodename if hasattr(os, 'uname') else 'unknown'
        }
        
        with open(self.lock_file_path, 'w') as f:
            json.dump(lock_info, f, indent=2)
    
    def _try_acquire_lock(self) -> bool:
        """Try to acquire the lock, handling stale locks."""
        try:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except IOError:
            # Lock is already held, check if the process is still running
            self._lock_fd.close()
            self._lock_fd = None
            
            # Read existing lock info
            existing_info = self._read_lock_info()
            if existing_info:
                existing_pid = existing_info.get('pid')
                if existing_pid and self._is_process_running(existing_pid):
                    # Process is still running, can't acquire lock
                    return False
                else:
                    # Process is not running, stale lock file, remove it
                    try:
                        self.lock_file_path.unlink()
                    except OSError as e:
                        logger.debug(f"Error removing stale lock file: {e}")
            
            # Try again to acquire the lock
            self._lock_fd = open(self.lock_file_path, 'a+')
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
    
    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful, False if already locked."""
        try:
            # Ensure the lock directory exists
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open the lock file
            self._lock_fd = open(self.lock_file_path, 'a+')
            
            # Try to acquire an exclusive lock (non-blocking)
            if not self._try_acquire_lock():
                return False
            
            # Write our process info to the lock file
            self._write_lock_info(
                os.getpid(), 
                str(self.config_path.resolve()), 
                time.time()
            )
            
            return True
            
        except (IOError, OSError) as e:
            logger.debug(f"Error acquiring lock: {e}")
            if self._lock_fd:
                try:
                    self._lock_fd.close()
                except Exception as close_error:
                    logger.debug(f"Error closing lock file descriptor: {close_error}")
                self._lock_fd = None
            return False
    
    def release(self):
        """Release the lock."""
        if self._lock_fd:
            try:
                # Release the file lock first, then remove the file
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
                # Remove the lock file after releasing the lock to avoid race condition
                try:
                    self.lock_file_path.unlink()
                except OSError as e:
                    logger.debug(f"Error removing lock file: {e}")
            except Exception as e:
                logger.debug(f"Error releasing lock: {e}")
            finally:
                self._lock_fd = None


def check_duplicate_instance(config_path: Optional[Path] = None) -> bool:
    """Check if another instance with the same config is running.
    
    Args:
        config_path: Path to config file to check for duplicates
        
    Returns:
        True if no duplicate instance found, False if duplicate exists
    """
    if config_path is None:
        from nanobot.config.paths import get_config_path
        config_path = get_config_path()
    
    lock_manager = LockManager(config_path)
    return lock_manager.acquire()


def release_instance_lock(config_path: Optional[Path] = None):
    """Release the instance lock for the given config path."""
    if config_path is None:
        from nanobot.config.paths import get_config_path
        config_path = get_config_path()
    
    lock_manager = LockManager(config_path)
    lock_manager.release()
