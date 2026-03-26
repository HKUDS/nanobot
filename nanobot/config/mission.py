"""Mission subsystem configuration."""

from __future__ import annotations

from nanobot.config.base import Base


class MissionConfig(Base):
    """Background mission tuning."""

    max_concurrent: int = 3
    max_iterations: int = 15
    result_max_chars: int = 4000
