"""Discord API tools for the agent."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordBaseTool(Tool):
    """Base class for Discord API tools."""

    def __init__(self, http_client: httpx.AsyncClient, token: str) -> None:
        self._http = http_client
        self._headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        }

    async def _api(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a Discord API call. Returns response JSON dict."""
        url = f"{DISCORD_API_BASE}{path}"
        try:
            resp = await self._http.request(
                method,
                url,
                headers=self._headers,
                content=json.dumps(json_data).encode() if json_data is not None else None,
            )
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}
        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.json().get("message", "")
            except Exception:
                pass
            return {"error": f"HTTP {e.response.status_code}: {error_body or str(e)}"}
        except Exception as e:
            return {"error": str(e)}


class DiscordSendTool(DiscordBaseTool):
    """Send a message to a Discord channel."""

    @property
    def name(self) -> str:
        return "discord_send"

    @property
    def description(self) -> str:
        return "Send a message to a Discord channel. Supports plain text or embed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Discord channel ID"},
                "content": {"type": "string", "description": "Text content to send"},
                "embed_title": {"type": "string", "description": "Optional embed title"},
                "embed_description": {"type": "string", "description": "Optional embed description"},
                "embed_color": {
                    "type": "integer",
                    "description": "Optional embed color (hex int, e.g. 0xFF0000)",
                },
            },
            "required": ["channel_id"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        channel_id = kwargs["channel_id"]
        payload: dict[str, Any] = {}
        if kwargs.get("content"):
            payload["content"] = kwargs["content"]
        if kwargs.get("embed_title") or kwargs.get("embed_description"):
            embed: dict[str, Any] = {}
            if kwargs.get("embed_title"):
                embed["title"] = kwargs["embed_title"]
            if kwargs.get("embed_description"):
                embed["description"] = kwargs["embed_description"]
            if kwargs.get("embed_color") is not None:
                embed["color"] = kwargs["embed_color"]
            payload["embeds"] = [embed]
        if not payload:
            return "Error: must provide content or embed_title/embed_description"
        result = await self._api("POST", f"/channels/{channel_id}/messages", payload)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Message sent (id={result.get('id', '?')})"


class DiscordCreateThreadTool(DiscordBaseTool):
    """Create a thread in a Discord channel."""

    @property
    def name(self) -> str:
        return "discord_create_thread"

    @property
    def description(self) -> str:
        return "Create a thread in a Discord channel, optionally from an existing message."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Discord channel ID"},
                "name": {"type": "string", "description": "Thread name (max 100 chars)"},
                "message_id": {
                    "type": "string",
                    "description": "Optional message ID to create thread from",
                },
                "auto_archive_duration": {
                    "type": "integer",
                    "description": "Minutes until auto-archive: 60, 1440, 4320, or 10080 (default 1440)",
                },
            },
            "required": ["channel_id", "name"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        channel_id = kwargs["channel_id"]
        name = kwargs["name"][:100]
        archive = kwargs.get("auto_archive_duration", 1440)
        payload: dict[str, Any] = {"name": name, "auto_archive_duration": archive}
        if kwargs.get("message_id"):
            path = f"/channels/{channel_id}/messages/{kwargs['message_id']}/threads"
        else:
            payload["type"] = 11  # GUILD_PUBLIC_THREAD
            path = f"/channels/{channel_id}/threads"
        result = await self._api("POST", path, payload)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Thread created (id={result.get('id', '?')}, name={result.get('name', '?')})"


class DiscordCreateChannelTool(DiscordBaseTool):
    """Create a channel in a Discord guild."""

    @property
    def name(self) -> str:
        return "discord_create_channel"

    @property
    def description(self) -> str:
        return "Create a channel in a Discord guild."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "guild_id": {"type": "string", "description": "Discord guild (server) ID"},
                "name": {"type": "string", "description": "Channel name"},
                "type": {
                    "type": "integer",
                    "description": "Channel type: 0=text, 2=voice, 4=category (default 0)",
                },
                "topic": {"type": "string", "description": "Optional channel topic"},
                "parent_id": {
                    "type": "string",
                    "description": "Optional category channel ID to nest under",
                },
            },
            "required": ["guild_id", "name"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        guild_id = kwargs["guild_id"]
        payload: dict[str, Any] = {
            "name": kwargs["name"],
            "type": kwargs.get("type", 0),
        }
        if kwargs.get("topic"):
            payload["topic"] = kwargs["topic"]
        if kwargs.get("parent_id"):
            payload["parent_id"] = kwargs["parent_id"]
        result = await self._api("POST", f"/guilds/{guild_id}/channels", payload)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Channel created (id={result.get('id', '?')}, name={result.get('name', '?')})"


class DiscordManageRolesTool(DiscordBaseTool):
    """Add or remove a role from a Discord guild member."""

    @property
    def name(self) -> str:
        return "discord_manage_roles"

    @property
    def description(self) -> str:
        return "Add or remove a role from a Discord guild member."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "guild_id": {"type": "string", "description": "Discord guild ID"},
                "user_id": {"type": "string", "description": "Discord user ID"},
                "role_id": {"type": "string", "description": "Discord role ID"},
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["add", "remove"],
                },
            },
            "required": ["guild_id", "user_id", "role_id", "action"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        guild_id = kwargs["guild_id"]
        user_id = kwargs["user_id"]
        role_id = kwargs["role_id"]
        action = kwargs["action"]
        path = f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
        if action == "add":
            result = await self._api("PUT", path)
        elif action == "remove":
            result = await self._api("DELETE", path)
        else:
            return f"Error: unknown action '{action}', must be 'add' or 'remove'"
        if "error" in result:
            return f"Error: {result['error']}"
        verb = "added to" if action == "add" else "removed from"
        return f"Role {role_id} {verb} user {user_id} successfully"


class DiscordCreateEmbedTool(DiscordBaseTool):
    """Send a rich embed message to a Discord channel."""

    @property
    def name(self) -> str:
        return "discord_create_embed"

    @property
    def description(self) -> str:
        return "Send a rich embed message to a Discord channel."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Discord channel ID"},
                "title": {"type": "string", "description": "Embed title"},
                "description": {"type": "string", "description": "Embed description"},
                "color": {"type": "integer", "description": "Embed color as integer (e.g. 0xFF0000)"},
                "fields": {
                    "type": "array",
                    "description": "List of embed fields",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "inline": {"type": "boolean"},
                        },
                        "required": ["name", "value"],
                    },
                },
                "footer": {"type": "string", "description": "Footer text"},
                "image_url": {"type": "string", "description": "URL of image to display in embed"},
            },
            "required": ["channel_id"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        channel_id = kwargs["channel_id"]
        embed: dict[str, Any] = {}
        if kwargs.get("title"):
            embed["title"] = kwargs["title"]
        if kwargs.get("description"):
            embed["description"] = kwargs["description"]
        if kwargs.get("color") is not None:
            embed["color"] = kwargs["color"]
        if kwargs.get("fields"):
            embed["fields"] = kwargs["fields"]
        if kwargs.get("footer"):
            embed["footer"] = {"text": kwargs["footer"]}
        if kwargs.get("image_url"):
            embed["image"] = {"url": kwargs["image_url"]}
        if not embed:
            return "Error: must provide at least one embed field (title, description, etc.)"
        result = await self._api("POST", f"/channels/{channel_id}/messages", {"embeds": [embed]})
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Embed sent (id={result.get('id', '?')})"


class DiscordPinMessageTool(DiscordBaseTool):
    """Pin or unpin a message in a Discord channel."""

    @property
    def name(self) -> str:
        return "discord_pin_message"

    @property
    def description(self) -> str:
        return "Pin or unpin a message in a Discord channel."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Discord channel ID"},
                "message_id": {"type": "string", "description": "Discord message ID"},
                "unpin": {
                    "type": "boolean",
                    "description": "If true, unpin the message instead (default false)",
                },
            },
            "required": ["channel_id", "message_id"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        channel_id = kwargs["channel_id"]
        message_id = kwargs["message_id"]
        unpin = kwargs.get("unpin", False)
        path = f"/channels/{channel_id}/pins/{message_id}"
        if unpin:
            result = await self._api("DELETE", path)
            action = "unpinned"
        else:
            result = await self._api("PUT", path)
            action = "pinned"
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Message {message_id} {action} successfully"


class DiscordPollTool(DiscordBaseTool):
    """Create a poll message in a Discord channel."""

    @property
    def name(self) -> str:
        return "discord_poll"

    @property
    def description(self) -> str:
        return "Create a poll message in a Discord channel."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Discord channel ID"},
                "question": {"type": "string", "description": "Poll question"},
                "answers": {
                    "type": "array",
                    "description": "List of answer options (2-10 items)",
                    "items": {"type": "string"},
                },
                "duration_hours": {
                    "type": "integer",
                    "description": "Poll duration in hours (default 24, max 168)",
                },
                "allow_multiselect": {
                    "type": "boolean",
                    "description": "Allow users to select multiple answers (default false)",
                },
            },
            "required": ["channel_id", "question", "answers"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        channel_id = kwargs["channel_id"]
        question = kwargs["question"]
        answers = kwargs["answers"]
        duration_hours = kwargs.get("duration_hours", 24)
        allow_multiselect = kwargs.get("allow_multiselect", False)

        if len(answers) < 2:
            return "Error: poll requires at least 2 answers"

        payload = {
            "poll": {
                "question": {"text": question},
                "answers": [{"poll_media": {"text": a}} for a in answers[:10]],
                "duration": duration_hours,
                "allow_multiselect": allow_multiselect,
            }
        }
        result = await self._api("POST", f"/channels/{channel_id}/messages", payload)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Poll created (id={result.get('id', '?')})"
