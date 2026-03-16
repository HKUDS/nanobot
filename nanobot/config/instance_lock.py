"""Instance lock and duplicate instance detection utilities."""

import os
import atexit
from pathlib import Path


# Global variable to track if we created a lock file
_created_lock_file: Path | None = None


def _get_lock_file_path(config_path: Path) -> Path:
    """Get the lock file path for a given config file."""
    return config_path.parent / f".{config_path.name}.lock"


def confirm_single_instance(config_path: Path) -> bool:
    """
    Check if a lock file exists and create one if not.
    
    Args:
        config_path: Path to the config file.
        
    Returns:
        True if we successfully created the lock file, False if one already exists.
    """
    lock_file = _get_lock_file_path(config_path)
    
    if lock_file.exists():
        # Check if the process that created the lock is still running
        try:
            with open(lock_file, 'r', encoding='utf-8') as f:
                pid = f.read().strip()
                if pid:
                    # Check if process is still running
                    if os.name == 'nt':
                        # Windows
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        process = kernel32.OpenProcess(1, 0, int(pid))
                        if process:
                            kernel32.CloseHandle(process)
                            return False
                    else:
                        # Unix-like
                        try:
                            os.kill(int(pid), 0)  # Send signal 0 to check if process exists
                            return False
                        except OSError:
                            # Process doesn't exist, lock file is stale
                            pass
        except Exception:
            pass
    
    # Create the lock file
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    
    global _created_lock_file
    _created_lock_file = lock_file
    
    # Register cleanup function to delete lock file on exit
    atexit.register(cleanup_lock)
    
    return True


def cleanup_lock() -> None:
    """Clean up the lock file if we created it."""
    global _created_lock_file
    if _created_lock_file and _created_lock_file.exists():
        try:
            _created_lock_file.unlink()
        except Exception:
            pass
        _created_lock_file = None
