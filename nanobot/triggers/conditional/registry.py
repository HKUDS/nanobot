"""Monitor registry — construction-time registration.

Each monitor registers via @register_monitor(monitor) or via a factory
registered with register_factory().  The runtime receives the resulting
dict and never imports monitors itself, decoupling the registry from
gateway wiring.
"""

from __future__ import annotations

from typing import Any, Callable

from nanobot.triggers.conditional.types import ConditionMonitor


_REGISTRY: dict[str, ConditionMonitor] = {}
_FACTORIES: dict[str, Callable[[], ConditionMonitor]] = {}


def register_monitor(monitor: ConditionMonitor) -> ConditionMonitor:
    if not getattr(monitor, "id", None):
        raise ValueError("monitor.id is required")
    _REGISTRY[monitor.id] = monitor
    return monitor


def register_factory(monitor_id: str, factory: Callable[[], ConditionMonitor]) -> None:
    if not monitor_id.strip():
        raise ValueError("monitor_id is required")
    _FACTORIES[monitor_id] = factory


def build_all_monitors() -> dict[str, ConditionMonitor]:
    """Return a snapshot combining eager + factory-built monitors."""
    out: dict[str, ConditionMonitor] = dict(_REGISTRY)
    for mid, fac in _FACTORIES.items():
        if mid in out:
            continue
        try:
            m = fac()
            if getattr(m, "id", "") != mid:
                # factory mismatch — keep factory's id but log via caller
                pass
            out[m.id] = m
        except Exception:
            continue
    return out


def clear_registry() -> None:
    _REGISTRY.clear()
    _FACTORIES.clear()


def list_registered_ids() -> list[str]:
    return sorted(set(list(_REGISTRY.keys()) + list(_FACTORIES.keys())))
