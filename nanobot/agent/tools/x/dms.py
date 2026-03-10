"""X DM tools — send, get events, get conversation via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XSendDmTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_send_dm"

    @property
    def description(self) -> str:
        return (
            "Send a direct message to a user on X. "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when confirming the sent message:\n"
            '::x-dm{text="<message_text>" participant="@<recipient_username>" size="default"}\n'
            "Replace placeholders with actual values. Use the recipient's username if available.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "participant_id": {"type": "string", "description": "The X user ID of the recipient."},
                "text": {"type": "string", "description": "The message text to send."},
            },
            "required": ["participant_id", "text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {
            "bot_id": bot_id,
            "participant_id": kwargs["participant_id"],
            "text": kwargs["text"],
        }
        return await self._post(f"{coordinator_url}/internal/x/dms/send", payload)


class XGetDmEventsTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_dm_events"

    @property
    def description(self) -> str:
        return (
            "Get recent DM events (messages) across all conversations on X. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH DM event in your response:\n"
            '::x-dm{text="<message_text>" participant="@<sender_username>" size="compact"}\n'
            "Use compact size when listing multiple messages. Replace placeholders with actual values from each event.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of DM events to return (1-100, default 10).",
                    "default": 10,
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id}
        if kwargs.get("max_results"):
            payload["max_results"] = kwargs["max_results"]
        return await self._post(f"{coordinator_url}/internal/x/dms/events", payload)


class XGetDmConversationTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_dm_conversation"

    @property
    def description(self) -> str:
        return (
            "Get DM events from a specific conversation on X by conversation ID. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH DM event in your response:\n"
            '::x-dm{text="<message_text>" participant="@<sender_username>" size="compact"}\n'
            "Use compact size when listing multiple messages. Replace placeholders with actual values from each event.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dm_conversation_id": {
                    "type": "string",
                    "description": "The DM conversation ID to retrieve messages from.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return (1-100, default 10).",
                    "default": 10,
                },
            },
            "required": ["dm_conversation_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {
            "bot_id": bot_id,
            "dm_conversation_id": kwargs["dm_conversation_id"],
        }
        if kwargs.get("max_results"):
            payload["max_results"] = kwargs["max_results"]
        return await self._post(f"{coordinator_url}/internal/x/dms/conversation", payload)
