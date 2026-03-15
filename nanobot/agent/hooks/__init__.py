"""Event-driven hook system."""

from nanobot.agent.hooks.base import Hook, HookEvent, HookResult
from nanobot.agent.hooks.filters import SkillsEnabledFilter
from nanobot.agent.hooks.json_loader import JsonConfigHook, load_hooks_from_json
from nanobot.agent.hooks.registry import HookRegistry
from nanobot.agent.hooks.storage import HookStorage

__all__ = [
    "Hook",
    "HookEvent",
    "HookRegistry",
    "HookResult",
    "HookStorage",
    "SkillsEnabledFilter",
    "JsonConfigHook",
    "load_hooks_from_json",
]
