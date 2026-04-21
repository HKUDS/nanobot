"""Identity helpers — distinct_id hashing."""

from __future__ import annotations

import hashlib
import os


def get_distinct_id(identifier: str, channel: str) -> str:
    """Return a stable SHA-256 hash for a channel identifier."""
    raw = f"{channel}:{identifier.strip()}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()


def get_household_id() -> str:
    """Return the household UUID from HOMER_HOUSEHOLD_ID env var."""
    return os.environ.get("HOMER_HOUSEHOLD_ID", "")
