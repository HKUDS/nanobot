"""HookCenter — typed-event registry and dispatch engine.

Guards, transforms, and observes are dispatched in strict order.
Internal handlers (session) run before external handlers (global).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.hooks.event_types import FinalizeContent as FinalizeContentEvent
from nanobot.hooks.event_types import OnStream, OnStreamEnd
from nanobot.hooks.protocols import Deny, HookHandler, HookResult, Modified

_STREAMING_EVENT_TYPES = (OnStream, OnStreamEnd)
_VALID_MODES = {"guard", "transform", "observe"}


@dataclass(slots=True)
class HookSession:
    internal_handlers: dict[type, dict[str, list[tuple[HookHandler, bool]]]] = field(
        default_factory=dict
    )
    wants_streaming_handlers: set[HookHandler] = field(default_factory=set)
    finalize_handlers: list[tuple[HookHandler, bool]] = field(default_factory=list)
    context: Any = field(default=None, init=False)
    """Placeholder for runner-provided AgentHookContext.  
    
    Set by AgentRunner.run() before each iteration.  Adapter wrappers read
    this reference to share the runner's mutable context object with
    legacy AgentHook subclasses.
    """


class HookCenter:
    __slots__ = ("_external_handlers",)

    def __init__(self) -> None:
        self._external_handlers: dict[type, dict[str, list[HookHandler]]] = {}

    # ------------------------------------------------------------------
    # registry
    # ------------------------------------------------------------------

    def register(self, event_type: type, handler: HookHandler, mode: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"Unknown mode {mode!r}; expected one of {_VALID_MODES}")
        if event_type not in self._external_handlers:
            self._external_handlers[event_type] = {"guard": [], "transform": [], "observe": []}
        group = self._external_handlers[event_type][mode]
        if handler not in group:
            group.append(handler)

    def register_internal(
        self,
        session: HookSession,
        event_type: type,
        handler: HookHandler,
        *,
        reraise: bool = False,
        mode: str = "observe",
        stream: bool = True,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"Unknown mode {mode!r}; expected one of {_VALID_MODES}")
        session.internal_handlers.setdefault(event_type, {"guard": [], "transform": [], "observe": []})
        group = session.internal_handlers[event_type][mode]
        item = (handler, reraise)
        if item not in group:
            group.append(item)
        if stream and event_type in _STREAMING_EVENT_TYPES:
            session.wants_streaming_handlers.add(handler)
        if event_type is FinalizeContentEvent:
            session.finalize_handlers.append((handler, reraise))

    def create_session(self) -> HookSession:
        return HookSession()

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    async def emit(self, event: Any, session: HookSession) -> HookResult:
        event_type = type(event)

        internal = session.internal_handlers.get(event_type, {})
        external = self._external_handlers.get(event_type, {})

        # guards: internal first, then external
        for handler, reraise in internal.get("guard", []):
            result: HookResult = await self._invoke_handler(handler, event, reraise)
            if isinstance(result, Deny):
                return result
        for handler in external.get("guard", []):
            result = await self._invoke_handler(handler, event, reraise=False)
            if isinstance(result, Deny):
                return result

        # transforms: internal first, then external
        for handler, reraise in internal.get("transform", []):
            result = await self._invoke_handler(handler, event, reraise)
            if isinstance(result, Modified):
                event = self._apply_modified(event, result)
        for handler in external.get("transform", []):
            result = await self._invoke_handler(handler, event, reraise=False)
            if isinstance(result, Modified):
                event = self._apply_modified(event, result)

        # observes: internal first, then external
        for handler, reraise in internal.get("observe", []):
            await self._invoke_handler(handler, event, reraise)
        for handler in external.get("observe", []):
            await self._invoke_handler(handler, event, reraise=False)

        return None

    def wants_streaming(self, session: HookSession) -> bool:
        if session.wants_streaming_handlers:
            return True
        for et in _STREAMING_EVENT_TYPES:
            if self._external_handlers.get(et):
                return True
        return False

    def finalize_content(self, content: str | None, session: HookSession) -> str | None:
        for handler, reraise in session.finalize_handlers:
            result, content = self._call_finalize_handler(handler, content, reraise)
            if isinstance(result, Deny):
                return content

        for handler in self._external_handlers.get(FinalizeContentEvent, {}).get("transform", []):
            result, content = self._call_finalize_handler(handler, content, reraise=False)
            if isinstance(result, Deny):
                return content

        return content

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _invoke_handler(
        handler: HookHandler, event: Any, reraise: bool
    ) -> HookResult:
        async def _call() -> HookResult:
            result = handler(event)
            if inspect.isawaitable(result):
                result = await result
            return result

        if reraise:
            return await _call()
        try:
            return await _call()
        except Exception:
            logger.exception(
                "HookCenter handler {} error in event {}",
                type(handler).__name__,
                type(event).__name__,
            )
            return None

    @staticmethod
    def _apply_modified(event: Any, modified: Modified) -> Any:
        data = modified.data
        if not isinstance(data, dict):
            logger.warning(
                "Transform handler returned non-dict Modified.data ({}) — "
                "event object replaced, downstream handlers may break",
                type(data).__name__,
            )
            return data
        for key, value in data.items():
            if hasattr(event, key):
                setattr(event, key, value)
            else:
                logger.debug(
                    "Modified.data key {!r} not found on event type {}",
                    key, type(event).__name__,
                )
        return event

    @staticmethod
    def _call_finalize_handler(
        handler: Any, content: str | None, reraise: bool
    ) -> tuple[HookResult, str | None]:
        try:
            result = handler(content)
        except Exception:
            if reraise:
                raise
            logger.exception("HookCenter finalize_content error in {}", type(handler).__name__)
            return None, content
        if isinstance(result, Modified):
            return result, result.data
        if isinstance(result, Deny):
            return result, content
        return None, result

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._external_handlers.clear()

    def discover(self, config: Any = None) -> None:
        from nanobot.hooks.discovery import register_discovered

        register_discovered(self, config)
