"""Backward-compat shim: re-exports ProfileStore as ProfileManager.

This file will be deleted after all imports are migrated in Task 3.
Do not add new code here.
"""
from __future__ import annotations

from .profile_io import (  # noqa: F401
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
    ProfileCache,
    ProfileStore,
)
from .profile_io import (
    ProfileStore as ProfileManager,  # noqa: F401
)

__all__ = [
    "PROFILE_KEYS",
    "PROFILE_STATUS_ACTIVE",
    "PROFILE_STATUS_CONFLICTED",
    "PROFILE_STATUS_STALE",
    "ProfileCache",
    "ProfileManager",
    "ProfileStore",
]
