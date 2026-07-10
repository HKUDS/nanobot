"""Config for the sustained-goal tools (``long_task`` / ``complete_goal``).

Kept in a dependency-light module (only ``config_base``) so that
``ToolsConfig`` can resolve its field type via ``model_rebuild()`` without
triggering the heavier import cycle of ``long_task.py`` (which pulls in
session/bus modules).
"""
from __future__ import annotations

from nanobot.config_base import Base


class LongTaskToolConfig(Base):
    """Feature flag for the sustained-goal behavior.

    Disabled by default: the sustained-goal auto-continuation can keep the agent
    working on a background goal during long main-thread tasks, blocking user
    interaction, and is not fully reliable yet. Opt in with
    ``tools.long_task.enable = true``.
    """

    enable: bool = False
