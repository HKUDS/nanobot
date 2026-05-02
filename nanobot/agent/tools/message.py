"""Message tool for sending messages to users."""

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import ArraySchema, StringSchema, tool_parameters_schema
from nanobot.bus.events import OutboundMessage
from nanobot.config.paths import get_workspace_path

_BUTTONS_DESCRIPTION = (
    "Inline interactive components for the user to click. "
    "USE this — do NOT describe buttons or menus in prose, and do NOT render "
    "them as markdown text. Each row is a list of cells; a cell is either a "
    "string (primary button label) or a dict. Examples:\n"
    '  buttons=[["Yes", "No"]]   # two primary buttons\n'
    '  buttons=[[{"type":"button","label":"Approve","style":"success"},'
    '{"type":"button","label":"Reject","style":"danger"}]]\n'
    '  buttons=[[{"type":"link","label":"Docs","url":"https://..."}]]\n'
    '  buttons=[[{"type":"select","custom_id":"pick","placeholder":"Pick one",'
    '"options":[{"label":"High","value":"high"},{"label":"Low","value":"low"}]}]]\n'
    '  buttons=[[{"type":"button","label":"Open form","custom_id":"notes-btn",'
    '"modal":{"title":"Notes","inputs":['
    '{"type":"text","label":"Notes","custom_id":"notes","max_length":1000}]}}]]\n'
    "Modal inputs support type=text (short), type=paragraph, type=radio "
    "(single-choice 1-of-N, options=[{label,value}], 2-10 options), "
    "type=checkbox (multi-choice, options=[…], min_values/max_values), "
    "and type=select (dropdown, options=[…], required). Modal cap is 5 inputs total. Example with mixed types:\n"
    '  buttons=[[{"type":"button","label":"Daily check-in","custom_id":"checkin",'
    '"modal":{"title":"Check-in","inputs":['
    '{"type":"text","custom_id":"sleep","label":"Hours of sleep"},'
    '{"type":"radio","custom_id":"energy","label":"Energy",'
    '"options":[{"label":"1 — drained","value":"1"},{"label":"2","value":"2"},'
    '{"label":"3","value":"3"},{"label":"4","value":"4"},{"label":"5 — fresh","value":"5"}]},'
    '{"type":"checkbox","custom_id":"tags","label":"Activities","min_values":1,"max_values":4,'
    '"options":[{"label":"Run","value":"run"},{"label":"Bike","value":"bike"},{"label":"Lift","value":"lift"}]}]}}]]\n'
    "Note: Discord rejects required=true with min_values=0. If a select/checkbox "
    "should be optional, either set min_values=1 (the default) or pass required=false."
    "Style: primary (default), secondary, success, danger. "
    "Discord renders every shape natively; other channels render labels only "
    "(select rows without scalar labels are dropped)."
)


@tool_parameters(
    tool_parameters_schema(
        content=StringSchema("The message content to send"),
        channel=StringSchema("Optional: target channel (telegram, discord, etc.)"),
        chat_id=StringSchema("Optional: target chat/user ID"),
        media=ArraySchema(
            StringSchema(""),
            description="Optional: list of file paths to attach (images, video, audio, documents)",
        ),
        buttons=ArraySchema(
            ArraySchema(
                # Cells are polymorphic: a string label or a component dict.
                # `oneOf` keeps the schema valid for strict providers (Mistral
                # 500s on items with no `type`) while letting models emit
                # either shape. Runtime validation in execute() enforces it.
                {
                    "oneOf": [
                        {
                            "type": "string",
                            "description": "Plain button label (renders as a primary button)",
                        },
                        {"type": "object", "description": "Component dict (button/link/select)"},
                    ],
                },
            ),
            description=_BUTTONS_DESCRIPTION,
        ),
        required=["content"],
    )
)
class MessageTool(Tool):
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
        self._workspace = (
            Path(workspace).expanduser() if workspace is not None else get_workspace_path()
        )
        self._default_channel: ContextVar[str] = ContextVar(
            "message_default_channel", default=default_channel
        )
        self._default_chat_id: ContextVar[str] = ContextVar(
            "message_default_chat_id", default=default_chat_id
        )
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

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set the current message context."""
        self._default_channel.set(channel)
        self._default_chat_id.set(chat_id)
        self._default_message_id.set(message_id)
        self._default_metadata.set(metadata or {})

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
            "Send a message to the user, optionally with file attachments or "
            "interactive components. "
            "This is the ONLY way to deliver files (images, documents, audio, video) to the user. "
            "Use the 'media' parameter with file paths to attach files. "
            "Use the 'buttons' parameter to offer choices, confirmations, menus, or "
            "fillable forms — emit them as components, do not describe them in prose. "
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
        **kwargs: Any,
    ) -> str:
        from nanobot.utils.helpers import strip_think

        content = strip_think(content)

        components: list[list[Any]] | None = None
        if buttons is not None:
            if not isinstance(buttons, list) or any(
                not isinstance(row, list) or any(not isinstance(cell, (str, dict)) for cell in row)
                for row in buttons
            ):
                return "Error: buttons must be a list of list of strings or component dicts"
            if any(any(isinstance(cell, dict) for cell in row) for row in buttons):
                # Rich component cells ride on metadata so non-Discord channels stay
                # untouched; we keep buttons as a label-only fallback for them.
                components = [list(row) for row in buttons]
                buttons = [
                    [
                        cell if isinstance(cell, str) else str(cell.get("label") or "")
                        for cell in row
                        if isinstance(cell, str) or (isinstance(cell, dict) and cell.get("label"))
                    ]
                    for row in buttons
                ]
                buttons = [row for row in buttons if row]
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
        if self._record_channel_delivery_var.get():
            metadata["_record_channel_delivery"] = True
        if components is not None:
            metadata["_components"] = components

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
            extra = ""
            if components is not None and channel != "discord":
                extra = f" (components rendered as labels on {channel})"
            return f"Message sent to {channel}:{chat_id}{media_info}{button_info}{extra}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
