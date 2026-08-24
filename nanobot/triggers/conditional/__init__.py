"""Gateway conditional-trigger runtime.

A single asyncio-managed runtime that hosts N pure-Python condition
monitors.  Monitors run on their own schedule, never touch the LLM
unless they decide to wake it, and de-duplicated/cooldown-gated hits are
enqueued into the workspace-local trigger store for agent delivery.
"""

from nanobot.triggers.conditional.registry import (
    build_all_monitors,
    clear_registry,
    list_registered_ids,
    register_factory,
    register_monitor,
)
from nanobot.triggers.conditional.runtime import ConditionalTriggerRuntime
from nanobot.triggers.conditional.state import ConditionalStateStore, MonitorStateRecord
from nanobot.triggers.conditional.types import (
    ConditionMonitor,
    MonitorAuditEvent,
    MonitorConfig,
    TriggerDecision,
)

__all__ = [
    "ConditionMonitor",
    "ConditionalStateStore",
    "ConditionalTriggerRuntime",
    "MonitorAuditEvent",
    "MonitorConfig",
    "MonitorStateRecord",
    "TriggerDecision",
    "build_all_monitors",
    "clear_registry",
    "list_registered_ids",
    "register_factory",
    "register_monitor",
]