"""Agents module with plugin support."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.agent.hook import AgentHook


class BaseAgent(ABC):
    """Abstract base class for nanobot agents.

    Agents extend the core agent loop with custom hooks, tools, and behaviors.
    They are discovered via the `nanobot.agents` entry point group.
    """

    name: str = "base"
    display_name: str = "Base Agent"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return default configuration for this agent."""
        return {}

    @classmethod
    @abstractmethod
    def create_hook(cls, **kwargs: Any) -> "AgentHook":
        """Factory method to create the agent's hook instance."""
        raise NotImplementedError


__all__ = ["BaseAgent"]
