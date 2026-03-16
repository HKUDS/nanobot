"""Interactive tools — ask_user_choice, confirm_action, ask_user_location."""

import asyncio
from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage

# Channels that support interactive UI (inline keyboards, reply keyboards).
# All other channels get a text fallback that the LLM can act on immediately.
_INTERACTIVE_CHANNELS = {"telegram"}


class _InteractiveToolBase(Tool):
    """Shared plumbing for tools that present interactive UI and await user input."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._pending: dict[str, asyncio.Future[str]] = {}

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        self._send_callback = callback

    def _supports_interactive(self, channel: str | None = None) -> bool:
        return (channel or self._default_channel) in _INTERACTIVE_CHANNELS

    def resolve(self, channel: str, chat_id: str, value: str) -> bool:
        """Resolve a pending selection. Returns True if a pending future was found."""
        key = f"{channel}:{chat_id}"
        future = self._pending.pop(key, None)
        if future and not future.done():
            future.set_result(value)
            return True
        return False

    def cancel_pending(self, channel: str, chat_id: str, reply_text: str | None = None) -> bool:
        """Cancel or resolve a pending future for a chat.

        If *reply_text* is provided the future is resolved with that value
        (so the tool returns the user's text to the LLM).  Otherwise the
        future is cancelled.  Returns True if a pending future existed.
        """
        key = f"{channel}:{chat_id}"
        future = self._pending.pop(key, None)
        if future and not future.done():
            if reply_text is not None:
                future.set_result(reply_text)
            else:
                future.cancel()
            return True
        return False

    async def _send_keyboard(
        self,
        text: str,
        buttons: list[dict[str, str]],
        columns: int,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> str:
        """Send an inline keyboard and block until the user taps a button."""
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"
        if not self._send_callback:
            return "Error: Message sending not configured"
        if not buttons:
            return "Error: At least one button is required"

        key = f"{channel}:{chat_id}"

        old_future = self._pending.pop(key, None)
        if old_future and not old_future.done():
            old_future.cancel()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[key] = future

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=text,
            metadata={
                "message_id": self._default_message_id,
                "interactive_buttons": {
                    "buttons": buttons,
                    "columns": columns,
                },
            },
        )

        try:
            await self._send_callback(msg)
        except Exception as e:
            self._pending.pop(key, None)
            return f"Error sending keyboard: {e}"

        try:
            value = await asyncio.wait_for(future, timeout=300)
            return value
        except asyncio.TimeoutError:
            self._pending.pop(key, None)
            return "__timeout__"
        except asyncio.CancelledError:
            return "__cancelled__"


class AskUserChoiceTool(_InteractiveToolBase):
    """Present the user with choices and wait for them to pick one."""

    @property
    def name(self) -> str:
        return "ask_user_choice"

    @property
    def description(self) -> str:
        return (
            "Present the user with a set of choices and wait for them to pick one. "
            "Use this whenever you want the user to choose between options — e.g. "
            "picking a movie, selecting a setting, confirming an action, etc. "
            "The choices are shown as interactive buttons the user can tap. "
            "The tool blocks until the user makes a selection or the timeout expires "
            "(5 minutes). Returns the value of the chosen option. "
            "Keep button values short (max 64 bytes)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The prompt or question to display above the buttons",
                },
                "buttons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "Button text shown to the user",
                            },
                            "value": {
                                "type": "string",
                                "description": "Value returned when the button is pressed (max 64 bytes)",
                            },
                        },
                        "required": ["label", "value"],
                    },
                    "description": "List of buttons to display",
                },
                "columns": {
                    "type": "integer",
                    "description": "Number of buttons per row (default: 2)",
                },
            },
            "required": ["text", "buttons"],
        }

    async def execute(
        self,
        text: str,
        buttons: list[dict[str, str]],
        columns: int = 2,
        channel: str | None = None,
        chat_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not self._supports_interactive(channel):
            options = "\n".join(f"  - {b['label']} ({b['value']})" for b in buttons)
            return (
                f"Interactive buttons are not supported on this channel. "
                f"Ask the user to reply with one of these options:\n{text}\n{options}"
            )
        result = await self._send_keyboard(text, buttons, columns, channel, chat_id)
        if result == "__timeout__":
            return "Timed out waiting for user selection (5 minutes)."
        if result == "__cancelled__":
            return "Selection cancelled."
        return f"User selected: {result}"


class ConfirmActionTool(_InteractiveToolBase):
    """Ask the user for Yes/No confirmation before proceeding."""

    @property
    def name(self) -> str:
        return "confirm_action"

    @property
    def description(self) -> str:
        return (
            "Ask the user to confirm or cancel an action. Shows a Yes/No prompt "
            "with interactive buttons. Use this before performing destructive, "
            "irreversible, or important operations — e.g. deleting files, sending "
            "messages on behalf of the user, making purchases, etc. "
            "Returns 'confirmed' or 'denied'. Blocks until the user responds "
            "or the timeout expires (5 minutes)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "What you are asking the user to confirm, e.g. 'Delete all completed downloads?'",
                },
                "yes_label": {
                    "type": "string",
                    "description": "Label for the confirm button (default: 'Yes')",
                },
                "no_label": {
                    "type": "string",
                    "description": "Label for the cancel button (default: 'No')",
                },
            },
            "required": ["text"],
        }

    async def execute(
        self,
        text: str,
        yes_label: str = "Yes",
        no_label: str = "No",
        channel: str | None = None,
        chat_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not self._supports_interactive(channel):
            return (
                f"Interactive buttons are not supported on this channel. "
                f"Ask the user to confirm by replying yes or no: {text}"
            )
        buttons = [
            {"label": yes_label, "value": "yes"},
            {"label": no_label, "value": "no"},
        ]
        result = await self._send_keyboard(text, buttons, columns=2, channel=channel, chat_id=chat_id)
        if result == "__timeout__":
            return "Timed out waiting for confirmation (5 minutes). Action NOT performed."
        if result == "__cancelled__":
            return "Confirmation cancelled. Action NOT performed."
        if result == "yes":
            return "confirmed"
        return "denied"


class AskUserLocationTool(_InteractiveToolBase):
    """Request the user's location via an interactive button."""

    @property
    def name(self) -> str:
        return "ask_user_location"

    @property
    def description(self) -> str:
        return (
            "Ask the user to share their current location. Shows a button that "
            "opens the device's GPS/location picker. Use this when you need the "
            "user's location — e.g. for weather, nearby places, directions, etc. "
            "Returns latitude and longitude. Blocks until the user shares their "
            "location or the timeout expires (5 minutes)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The prompt explaining why you need their location, e.g. 'Share your location so I can check the weather'",
                },
            },
            "required": ["text"],
        }

    async def execute(
        self,
        text: str,
        channel: str | None = None,
        chat_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id

        if not self._supports_interactive(channel):
            return (
                f"Location sharing buttons are not supported on this channel. "
                f"Ask the user to provide their location as text instead."
            )

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"
        if not self._send_callback:
            return "Error: Message sending not configured"

        key = f"{channel}:{chat_id}"

        old_future = self._pending.pop(key, None)
        if old_future and not old_future.done():
            old_future.cancel()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[key] = future

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=text,
            metadata={
                "message_id": self._default_message_id,
                "request_location": True,
            },
        )

        try:
            await self._send_callback(msg)
        except Exception as e:
            self._pending.pop(key, None)
            return f"Error requesting location: {e}"

        try:
            value = await asyncio.wait_for(future, timeout=300)
            return f"User location: {value}"
        except asyncio.TimeoutError:
            self._pending.pop(key, None)
            return "Timed out waiting for location (5 minutes)."
        except asyncio.CancelledError:
            return "Location request cancelled."
