"""nanobot/plugins/__init__.py - Plugin loader."""

from loguru import logger

# Import plugins to ensure they register their hooks
# This happens at module import time


def load_plugins():
    """Load all plugins. Called at startup."""
    try:
        # Import Core Plugin - This Registers all Hooks
        from . import core

        logger.info("Loaded Telegram UI plugin")
    except ImportError as e:
        logger.warning(f"Could not load Core Plugin: {e}")

    # Add more Plugins Here as needed


def init():
    """Initialize plugins - loads all plugins."""
    load_plugins()


# Auto-load on Import
load_plugins()
