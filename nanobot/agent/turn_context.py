"""Per-turn tool context wiring.

Sets routing context (channel, chat_id) on tools that need it, and
manages the per-session scratchpad lifecycle.

Extracted from ``MessageProcessor._set_tool_context`` and
``MessageProcessor._ensure_scratchpad``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from nanobot.context.context import ContextBuilder
    from nanobot.coordination.delegation import DelegationDispatcher
    from nanobot.coordination.mission import MissionManager
    from nanobot.coordination.scratchpad import Scratchpad
    from nanobot.tools.executor import ToolExecutor


class TurnContextManager:
    """Sets per-turn context on routing-aware tools."""

    def __init__(
        self,
        *,
        tools: ToolExecutor,
        dispatcher: DelegationDispatcher,
        missions: MissionManager,
        context: ContextBuilder,
        scratchpad_factory: Callable[[Path], Scratchpad] | None = None,
    ) -> None:
        self._tools = tools
        self._dispatcher = dispatcher
        self._missions = missions
        self._context = context
        self._scratchpad_factory = scratchpad_factory
        self._scratchpad: Scratchpad | None = None
        self._contacts_provider: Callable[[], list[str]] | None = None

    @property
    def scratchpad(self) -> Scratchpad | None:
        """Current session scratchpad, if initialised."""
        return self._scratchpad

    def set_contacts_provider(self, provider: Callable[[], list[str]]) -> None:
        """Set callback that returns known contacts."""
        self._contacts_provider = provider

    def set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update per-turn context for all context-aware tools."""
        if self._contacts_provider is not None:
            self._context.set_contacts_context(self._contacts_provider())

        for tool in self._tools.all_tools():
            tool.set_context(
                channel=channel,
                chat_id=chat_id,
                message_id=message_id,
                session_key=f"{channel}:{chat_id}",
            )

    def ensure_scratchpad(self, session_key: str, workspace: Path) -> None:
        """Create or retrieve per-session scratchpad and update tools."""
        from nanobot.utils.paths import safe_filename

        safe_key = safe_filename(session_key.replace(":", "_"))
        session_dir = workspace / "sessions" / safe_key
        session_dir.mkdir(parents=True, exist_ok=True)
        if self._scratchpad_factory:
            self._scratchpad = self._scratchpad_factory(session_dir)

        # Update subsystem references via public setters
        self._dispatcher.scratchpad = self._scratchpad
        self._dispatcher.set_trace_path(session_dir / "routing_trace.jsonl")
        self._missions.scratchpad = self._scratchpad

        # Update scratchpad on all tools via lifecycle hook
        for tool in self._tools.all_tools():
            tool.on_session_change(scratchpad=self._scratchpad)
