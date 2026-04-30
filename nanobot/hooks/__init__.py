"""HookCenter — typed-event hook system for nanobot.

Provides:
- Typed event dataclasses for agent lifecycle hooks
- Handler Protocol and return types (Modified, Deny)
- HookCenter registry and dispatch engine
- Entry-point plugin discovery
- AgentHook compatibility adapter
"""

from nanobot.hooks.event_types import (
    AfterIteration,
    BeforeExecuteTools,
    BeforeIteration,
    FinalizeContent,
    OnStream,
    OnStreamEnd,
)
from nanobot.hooks.protocols import Deny, HookHandler, HookResult, Modified

__all__ = [
    "AfterIteration",
    "BeforeExecuteTools",
    "BeforeIteration",
    "Deny",
    "FinalizeContent",
    "HookHandler",
    "HookResult",
    "Modified",
    "OnStream",
    "OnStreamEnd",
]
