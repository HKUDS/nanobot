"""Hook system for nanobot — extensible event-driven callbacks."""

from nanobot.hooks.base import Hook, HookContext
from nanobot.hooks.manager import HookManager

__all__ = ["Hook", "HookContext", "HookManager"]
