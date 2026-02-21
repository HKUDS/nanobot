"""nanobot/plugins/__init__.py - Plugin loader."""

from loguru import logger

# Import plugins to ensure they register their hooks
# This happens at module import time


def load_plugins():
    """Load all plugins. Called at startup."""
    try:
        # Import core plugin - this registers all hooks
        from . import core

        logger.info("Loaded Telegram UI plugin")
    except ImportError as e:
        logger.warning(f"Could not load core plugin: {e}")

    # Add more plugins here as needed


# Auto-load on import
load_plugins()
