"""
Entry point for running nanobot as a module: python -m nanobot
"""

# CRITICAL: Set up async library detection before anything else
# This prevents AsyncLibraryNotFoundError and anyio task corruption 
# when threads or subprocesses interfere with the async context
import sniffio
import asyncio
import sys
from functools import wraps
from typing import Any

# Force set the async library to asyncio at startup
sniffio._impl.current_async_library_cvar.set("asyncio")

# Monkey-patch sniffio to always return asyncio as a fallback
_original_current_async_library = sniffio.current_async_library

def _patched_current_async_library():
    try:
        return _original_current_async_library()
    except sniffio.AsyncLibraryNotFoundError:
        import logging
        logging.getLogger("nanobot.fixes").debug(
            "sniffio.AsyncLibraryNotFoundError detected, returning 'asyncio' as fallback. "
            "This usually happens when subprocesses or threads corrupt the async context."
        )
        return "asyncio"

sniffio.current_async_library = _patched_current_async_library

# CRITICAL FIX: Patch httpcore's AsyncShieldCancellation to handle corrupted async context
# This prevents "cannot create weak reference to 'NoneType' object" errors
# when IPython threads corrupt the async context
try:
    import httpcore._synchronization as _httpcore_sync
    import anyio
    
    _original_async_shield_init = _httpcore_sync.AsyncShieldCancellation.__init__
    _original_async_shield_enter = _httpcore_sync.AsyncShieldCancellation.__enter__
    _original_async_shield_exit = _httpcore_sync.AsyncShieldCancellation.__exit__
    
    def _patched_async_shield_init(self):
        """Initialize with error handling for corrupted context."""
        try:
            _original_async_shield_init(self)
        except Exception:
            # Context is corrupted, mark as disabled
            self._backend = None
            self._anyio_shield = None
            self._trio_shield = None
    
    def _patched_async_shield_enter(self):
        """Enter with error handling."""
        if getattr(self, '_backend', None) is None:
            # Disabled due to corrupted context, just return self
            return self
        try:
            return _original_async_shield_enter(self)
        except Exception:
            # Failed to enter, mark as entered to allow exit
            return self
    
    def _patched_async_shield_exit(self, exc_type=None, exc_value=None, traceback=None):
        """Exit with error handling."""
        if getattr(self, '_backend', None) is None:
            # Was disabled, nothing to exit
            return None
        try:
            return _original_async_shield_exit(self, exc_type, exc_value, traceback)
        except Exception:
            # Failed to exit, suppress error
            return None
    
    _httpcore_sync.AsyncShieldCancellation.__init__ = _patched_async_shield_init
    _httpcore_sync.AsyncShieldCancellation.__enter__ = _patched_async_shield_enter
    _httpcore_sync.AsyncShieldCancellation.__exit__ = _patched_async_shield_exit
    
except Exception:
    pass

from nanobot.cli.commands import app

if __name__ == "__main__":
    app()
