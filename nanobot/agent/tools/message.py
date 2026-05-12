"""Message tool for sending messages to users."""

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import ArraySchema, StringSchema, tool_parameters_schema
from nanobot.bus.events import OutboundMessage
from nanobot.config.paths import get_workspace_path


@tool_parameters(
    tool_parameters_schema(
        content=StringSchema(
            "Message content for proactive or cross-channel delivery. "
            "Do not use this for a normal reply in the current chat."
        ),
        channel=StringSchema(
            "Optional target channel for cross-channel/proactive delivery. "
            "Do not set this to the current runtime channel for a normal reply."
        ),
        chat_id=StringSchema(
            "Optional target chat/user ID for cross-channel/proactive delivery. "
            "Do not set this to the current runtime chat for a normal reply."
        ),
        media=ArraySchema(
            StringSchema(""),
            description=(
                "Optional list of existing file paths to attach for proactive or cross-channel delivery. "
                "Do not use this to resend generate_image outputs in the current chat."
            ),
        ),
        buttons=ArraySchema(
            ArraySchema(StringSchema("Button label")),
            description="Optional: inline keyboard buttons as list of rows, each row is list of button labels.",
        ),
        required=["content"],
    )
)
class MessageTool(Tool, ContextAware):
    """Tool to send messages to users on chat channels."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
        workspace: str | Path | None = None,
    ):
        self._send_callback = send_callback
        self._workspace = Path(workspace).expanduser() if workspace is not None else get_workspace_path()
        self._default_channel: ContextVar[str] = ContextVar("message_default_channel", default=default_channel)
        self._default_chat_id: ContextVar[str] = ContextVar("message_default_chat_id", default=default_chat_id)
        self._default_message_id: ContextVar[str | None] = ContextVar(
            "message_default_message_id",
            default=default_message_id,
        )
        self._default_metadata: ContextVar[dict[str, Any]] = ContextVar(
            "message_default_metadata",
            default={},
        )
        self._sent_in_turn_var: ContextVar[bool] = ContextVar("message_sent_in_turn", default=False)
        self._record_channel_delivery_var: ContextVar[bool] = ContextVar(
            "message_record_channel_delivery",
            default=False,
        )

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        send_callback = ctx.bus.publish_outbound if ctx.bus else None
        return cls(send_callback=send_callback, workspace=ctx.workspace)

    def set_context(self, ctx: RequestContext) -> None:
        """Set the current message context."""
        self._default_channel.set(ctx.channel)
        self._default_chat_id.set(ctx.chat_id)
        self._default_message_id.set(ctx.message_id)
        self._default_metadata.set(dict(ctx.metadata or {}))

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    def start_turn(self) -> None:
        """Reset per-turn send tracking."""
        self._sent_in_turn = False

    def set_record_channel_delivery(self, active: bool):
        """Mark tool-sent messages as proactive channel deliveries."""
        return self._record_channel_delivery_var.set(active)

    def reset_record_channel_delivery(self, token) -> None:
        """Restore previous proactive delivery recording state."""
        self._record_channel_delivery_var.reset(token)

    @property
    def _sent_in_turn(self) -> bool:
        return self._sent_in_turn_var.get()

    @_sent_in_turn.setter
    def _sent_in_turn(self, value: bool) -> None:
        self._sent_in_turn_var.set(value)

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return (
            "Proactively send a message to a user/channel, optionally with file attachments. "
            "Use this for reminders, cross-channel delivery, or explicit proactive sends. "
            "Do not use this for the normal reply in the current chat: answer naturally instead. "
            "If channel/chat_id would target the current runtime conversation, do not call this tool "
            "unless the user explicitly asked you to proactively send an existing file attachment. "
            "When generate_image creates images in the current chat, the final assistant reply "
            "automatically attaches them; do not call message just to announce or resend them. "
            "For proactive attachment delivery, use the 'media' parameter with file paths. "
            "Do NOT use read_file to send files — that only reads content for your own analysis."
        )

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        buttons: list[list[str]] | None = None,
        **kwargs: Any
    ) -> str:
        from nanobot.utils.helpers import strip_think
        content = strip_think(content)

        if buttons is not None:
            if not isinstance(buttons, list) or any(
                not isinstance(row, list) or any(not isinstance(label, str) for label in row)
                for row in buttons
            ):
                return "Error: buttons must be a list of list of strings"
        default_channel = self._default_channel.get()
        default_chat_id = self._default_chat_id.get()
        channel = channel or default_channel
        chat_id = chat_id or default_chat_id
        # Only inherit default message_id when targeting the same channel+chat.
        # Cross-chat sends must not carry the original message_id, because
        # some channels (e.g. Feishu) use it to determine the target
        # conversation via their Reply API, which would route the message
        # to the wrong chat entirely.
        same_target = channel == default_channel and chat_id == default_chat_id
        if same_target:
            message_id = message_id or self._default_message_id.get()
        else:
            message_id = None

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"

        if media:
            resolved = []
            for p in media:
                if p.startswith(("http://", "https://")) or os.path.isabs(p):
                    resolved.append(p)
                else:
                    resolved.append(str(self._workspace / p))
            media = resolved

        metadata = dict(self._default_metadata.get()) if same_target else {}
        if message_id:
            metadata["message_id"] = message_id
        if self._record_channel_delivery_var.get() or media:
            metadata["_record_channel_delivery"] = True

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            buttons=buttons or [],
            metadata=metadata,
        )

        try:
            await self._send_callback(msg)
            if channel == default_channel and chat_id == default_chat_id:
                self._sent_in_turn = True
            media_info = f" with {len(media)} attachments" if media else ""
            button_info = f" with {sum(len(row) for row in buttons)} button(s)" if buttons else ""
            return f"Message sent to {channel}:{chat_id}{media_info}{button_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
