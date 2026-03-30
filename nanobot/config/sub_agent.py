"""Shared sub-agent execution parameters.

``SubAgentConfig`` captures the parameters that govern how a sub-agent
tool loop runs — used by ``MissionManager``.
"""

from __future__ import annotations

from pathlib import Path

from nanobot.config.base import Base


class SubAgentConfig(Base):
    """Execution parameters for a sub-agent tool loop."""

    workspace: Path
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
