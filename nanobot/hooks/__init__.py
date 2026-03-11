"""Hook system for nanobot — extensible event-driven callbacks."""

from nanobot.hooks.base import Hook, HookContext
from nanobot.hooks.manager import HookManager
from nanobot.hooks.self_improvement import SelfImprovementHook

__all__ = ["Hook", "HookContext", "HookManager", "SelfImprovementHook"]
