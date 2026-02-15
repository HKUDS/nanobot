"""nanobot/system/hooks.py - Event hook system for plugins."""

import asyncio
from typing import Any, Callable, Dict, List, Optional
from loguru import logger


class HookManager:
    """Event hook manager for decoupled plugin architecture."""

    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def register(self, event_name: str, handler: Callable):
        """Register a handler for an event."""
        if event_name not in self._hooks:
            self._hooks[event_name] = []
        self._hooks[event_name].append(handler)
        logger.debug(f"Registered handler for {event_name}")

    async def emit(self, event_name: str, **kwargs) -> List[Any]:
        """Emit an event to all registered handlers.

        Returns list of results from all handlers.
        """
        results = []
        if event_name not in self._hooks:
            return results

        for handler in self._hooks[event_name]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(**kwargs)
                else:
                    result = handler(**kwargs)
                results.append(result)
            except AssertionError as e:
                logger.critical(f"Assertion failed in hook {event_name}: {e}")
                raise  # Crash on assertion failures - fail fast
            except Exception as e:
                logger.error(f"Error in hook {event_name}: {e}")

        return results

    def emit_sync(self, event_name: str, **kwargs) -> List[Any]:
        """Emit an event synchronously (for non-async contexts)."""
        results = []
        if event_name not in self._hooks:
            return results

        for handler in self._hooks[event_name]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    # Schedule async handler
                    asyncio.create_task(handler(**kwargs))
                else:
                    result = handler(**kwargs)
                    results.append(result)
            except AssertionError as e:
                logger.critical(f"Assertion failed in sync hook {event_name}: {e}")
                raise  # Crash on assertion failures - fail fast
            except Exception as e:
                logger.error(f"Error in sync hook {event_name}: {e}")

        return results


# Global singleton instance
_hook_manager_instance: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """Get the global hook manager instance."""
    global _hook_manager_instance
    if _hook_manager_instance is None:
        _hook_manager_instance = HookManager()
    return _hook_manager_instance


# Convenience import
hook_manager = get_hook_manager()
