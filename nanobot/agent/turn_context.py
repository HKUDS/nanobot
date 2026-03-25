"""Per-turn tool context wiring.

Sets routing context (channel, chat_id) on tools that need it, and
manages the per-session scratchpad lifecycle.

Extracted from ``MessageProcessor._set_tool_context`` and
``MessageProcessor._ensure_scratchpad``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from nanobot.tools.builtin.message import MessageTool
from nanobot.tools.builtin.scratchpad import ScratchpadReadTool, ScratchpadWriteTool

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
    ) -> None:
        self._tools = tools
        self._dispatcher = dispatcher
        self._missions = missions
        self._context = context
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
        from nanobot.tools.builtin.cron import CronTool
        from nanobot.tools.builtin.feedback import FeedbackTool
        from nanobot.tools.builtin.mission import MissionStartTool

        if self._contacts_provider is not None:
            self._context.set_contacts_context(self._contacts_provider())

        msg_t = self._tools.get("message")
        if isinstance(msg_t, MessageTool):
            msg_t.set_context(channel, chat_id, message_id)
        ms_t = self._tools.get("mission_start")
        if isinstance(ms_t, MissionStartTool):
            ms_t.set_context(channel, chat_id)
        cr_t = self._tools.get("cron")
        if isinstance(cr_t, CronTool):
            cr_t.set_context(channel, chat_id)
        fb_t = self._tools.get("feedback")
        if isinstance(fb_t, FeedbackTool):
            fb_t.set_context(channel, chat_id, session_key=f"{channel}:{chat_id}")

    def ensure_scratchpad(self, session_key: str, workspace: Path) -> None:
        """Create or retrieve per-session scratchpad and update tools."""
        from nanobot.coordination.scratchpad import Scratchpad
        from nanobot.utils.helpers import safe_filename

        safe_key = safe_filename(session_key.replace(":", "_"))
        session_dir = workspace / "sessions" / safe_key
        session_dir.mkdir(parents=True, exist_ok=True)
        self._scratchpad = Scratchpad(session_dir)

        # Update subsystem references via public setters
        self._dispatcher.scratchpad = self._scratchpad
        self._dispatcher.set_trace_path(session_dir / "routing_trace.jsonl")
        self._missions.scratchpad = self._scratchpad

        # Update scratchpad tool references via public setters
        write_tool = self._tools.get("write_scratchpad")
        if isinstance(write_tool, ScratchpadWriteTool):
            write_tool.set_scratchpad(self._scratchpad)
        read_tool = self._tools.get("read_scratchpad")
        if isinstance(read_tool, ScratchpadReadTool):
            read_tool.set_scratchpad(self._scratchpad)
