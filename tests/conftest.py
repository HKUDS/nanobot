"""Pytest configuration for nanobot tests."""

import pytest


@pytest.fixture(autouse=True)
def enable_asyncio_auto_mode():
    """Auto-configure asyncio mode for all async tests."""
    pass
