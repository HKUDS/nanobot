"""Channel-related tools for the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.channels.manager import ChannelManager


class ChannelInfoTool(Tool):
    """Tool to list enabled channels, their status, and available channel-specific tools."""

    def __init__(self, channel_manager: ChannelManager):
        self._cm = channel_manager

    @property
    def name(self) -> str:
        return "channel_info"

    @property
    def description(self) -> str:
        return (
            "List enabled chat channels, their running status, and any "
            "channel-specific tools they provide (e.g. feishu_create_doc). "
            "Optionally pass a channel name for details about that channel only."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Optional: a specific channel name to get details for",
                },
            },
            "required": [],
        }

    async def execute(self, channel: str | None = None, **kwargs: Any) -> str:
        channels = self._cm.channels

        if channel:
            ch = channels.get(channel)
            if not ch:
                available = ", ".join(channels.keys()) or "(none)"
                return f"Channel '{channel}' not found. Enabled channels: {available}"
            return self._format_channel(channel, ch)

        if not channels:
            return "No channels are currently enabled."

        parts = ["Enabled channels:"]
        for ch_name, ch in channels.items():
            parts.append(self._format_channel(ch_name, ch))
        return "\n".join(parts)

    @staticmethod
    def _format_channel(name: str, ch: Any) -> str:
        status = "running" if ch.is_running else "stopped"
        tools = ch.get_tools()
        tool_names = [t.name for t in tools]
        tools_str = ", ".join(tool_names) if tool_names else "(none)"
        return f"  {name} ({status}) — tools: {tools_str}"
